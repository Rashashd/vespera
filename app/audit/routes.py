"""Audit-log viewer endpoint (staff oversight): GET /audit — read-only, cross-client.

The audit_log is append-only (FR-013/FR-014); this exposes it read-only to staff
(manager + admin) so they can review all changes and report outcomes across clients.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.audit.schemas import AUDIT_CATEGORIES, AuditEntryOut
from app.auth.dependencies import require_admin
from app.auth.models import User
from app.core.dependencies import get_session

router = APIRouter(prefix="/audit", tags=["audit"])

# Auth/access events are noise in a *changes & outcomes* viewer — never surfaced here.
# (Login monitoring, if needed, belongs in a dedicated security view, not this one.)
_EXCLUDED_EVENT_TYPES = ("UserLoggedIn", "LoginFailed", "UserLoggedOut")


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
