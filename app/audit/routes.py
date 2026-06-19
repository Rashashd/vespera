"""Audit-log viewer endpoint (staff oversight): GET /audit — read-only, cross-client.

The audit_log is append-only (FR-013/FR-014); this exposes it read-only to staff
(manager + admin) so they can review all changes and report outcomes across clients.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.audit.schemas import AUDIT_CATEGORIES, AuditEntryOut
from app.auth.dependencies import require_admin
from app.auth.models import User
from app.auth.schemas import Role
from app.core.dependencies import get_session
from app.domain.events import AuditExported

router = APIRouter(prefix="/audit", tags=["audit"])

# Auth/access events are noise in a *changes & outcomes* viewer — never surfaced here.
# (Login monitoring, if needed, belongs in a dedicated security view, not this one.)
_EXCLUDED_EVENT_TYPES = ("UserLoggedIn", "LoginFailed", "UserLoggedOut")

# Spec 13 FR-018: an admin sees ONLY client/watchlist-management events; a manager sees all;
# a reviewer is denied entirely (require_admin already excludes reviewers).
_ADMIN_VISIBLE_EVENTS = (
    "ClientCreated",
    "ClientUpdated",
    "ClientSuspended",
    "ClientReactivated",
    "ClientReportEmailChanged",
    "ClientUserCreated",
    "ClientUserScopeChanged",
    "WatchlistCreated",
    "WatchlistUpdated",
    "WatchlistDeactivated",
    "WatchlistItemAdded",
    "WatchlistItemRemoved",
    "WatchlistActivationChanged",
)


def _is_manager(staff: User) -> bool:
    """Manager = superuser audit visibility (all events); admin = client/watchlist scope only."""
    return staff.role == Role.MANAGER.value


@router.get("", response_model=list[AuditEntryOut])
async def list_audit_log(
    category: str | None = Query(None, description="reports | findings | clients | jobs"),
    event_type: str | None = Query(None, description="Exact domain-event class name"),
    client_id: int | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    staff: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[AuditEntryOut]:
    """Return change/outcome audit entries newest-first; staff-only (FR-013/FR-014)."""
    q = (
        select(AuditLog)
        .where(AuditLog.event_type.notin_(_EXCLUDED_EVENT_TYPES))
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    )
    # FR-018: an admin (not manager) sees only client/watchlist-management events.
    if not _is_manager(staff):
        q = q.where(AuditLog.event_type.in_(_ADMIN_VISIBLE_EVENTS))

    if category is not None:
        if category not in AUDIT_CATEGORIES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="UNKNOWN_CATEGORY")
        q = q.where(AuditLog.event_type.in_(AUDIT_CATEGORIES[category]))
    if event_type is not None:
        q = q.where(AuditLog.event_type == event_type)
    if client_id is not None:
        q = q.where(AuditLog.client_id == client_id)

    q = q.limit(limit).offset(offset)
    rows = (await session.execute(q)).scalars().all()
    return [AuditEntryOut.model_validate(r) for r in rows]


_CSV_COLUMNS = ("id", "created_at", "actor_id", "actor_type", "event_type", "target", "client_id")


@router.get("/export")
async def export_audit_log(
    request: Request,
    format: str = Query("csv", pattern="^(csv|json)$"),
    category: str | None = Query(None),
    event_type: str | None = Query(None),
    client_id: int | None = Query(None),
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None),
    limit: int = Query(1000, ge=1, le=10000),
    staff: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Export the (role-filtered) audit log as CSV or JSON; the export itself is audited (FR-018).

    Manager → all events; admin → client/watchlist-management only; reviewer → 403 (require_admin).
    Bounded by `limit` (≤10000) so the append-only log never streams unbounded.
    """
    q = (
        select(AuditLog)
        .where(AuditLog.event_type.notin_(_EXCLUDED_EVENT_TYPES))
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    )
    scope = "all"
    if not _is_manager(staff):
        q = q.where(AuditLog.event_type.in_(_ADMIN_VISIBLE_EVENTS))
        scope = "client_watchlist"

    if category is not None:
        if category not in AUDIT_CATEGORIES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="UNKNOWN_CATEGORY")
        q = q.where(AuditLog.event_type.in_(AUDIT_CATEGORIES[category]))
    if event_type is not None:
        q = q.where(AuditLog.event_type == event_type)
    if client_id is not None:
        q = q.where(AuditLog.client_id == client_id)
    if from_ is not None:
        q = q.where(AuditLog.created_at >= from_)
    if to is not None:
        q = q.where(AuditLog.created_at <= to)

    rows = (await session.execute(q.limit(limit))).scalars().all()
    entries = [AuditEntryOut.model_validate(r) for r in rows]

    # The export is itself an audited event (append-only; FR-018).
    await request.app.state.dispatcher.dispatch(
        AuditExported(
            actor_id=staff.id,
            actor_type="human",
            client_id=client_id,
            format=format,
            scope=scope,
        ),
        session,
    )

    if format == "json":
        body = json.dumps([e.model_dump(mode="json") for e in entries])
        media, filename = "application/json", "audit-export.json"
    else:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([*_CSV_COLUMNS, "payload"])
        for e in entries:
            writer.writerow(
                [
                    e.id,
                    e.created_at.isoformat(),
                    e.actor_id,
                    e.actor_type,
                    e.event_type,
                    e.target,
                    e.client_id if e.client_id is not None else "",
                    json.dumps(e.payload or {}),
                ]
            )
        body, media, filename = buf.getvalue(), "text/csv", "audit-export.csv"

    return Response(
        content=body,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
