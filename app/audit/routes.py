"""Audit-log viewer endpoint (staff oversight): GET /audit — read-only, cross-client.

The audit_log is append-only (FR-013/FR-014); this exposes it read-only to staff
(manager + admin) so they can review all changes and report outcomes across clients. The
role-scoped visibility policy + query building live in ``app/audit/service.py``; these routes
handle validation, pagination, and response shaping (list / CSV-JSON export).
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit_service
from app.audit.schemas import AUDIT_CATEGORIES, AuditEntryOut
from app.auth.dependencies import require_admin
from app.auth.models import User
from app.core.dependencies import get_session
from app.domain.events import AuditExported

router = APIRouter(prefix="/audit", tags=["audit"])


def _validate_category(category: str | None) -> None:
    """Reject an unknown category at the HTTP boundary (400) before building the query."""
    if category is not None and category not in AUDIT_CATEGORIES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="UNKNOWN_CATEGORY")


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
    _validate_category(category)
    q, _ = audit_service.build_scoped_query(
        staff, category=category, event_type=event_type, client_id=client_id
    )
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
    _validate_category(category)
    q, scope = audit_service.build_scoped_query(
        staff,
        category=category,
        event_type=event_type,
        client_id=client_id,
        from_=from_,
        to=to,
    )
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
