"""Scheduling endpoints: cycle status, cycle abandon, dead-letter admin (spec 11)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_acting_client_read, require_manager, require_staff
from app.auth.models import User
from app.clients.models import Client
from app.core.dependencies import get_session
from app.scheduling.models import DeadLetter, WatchlistCycle

router = APIRouter(tags=["scheduling"])


# ── Schemas ───────────────────────────────────────────────────────────────────


class CycleOut(BaseModel):
    """Cycle summary for operator/reviewer visibility."""

    id: int
    watchlist_id: int
    client_id: int
    status: str
    current_stage: str
    cadence_at_start: str
    period_start: datetime
    period_end: datetime
    ingestion_run_id: int | None
    index_build_run_id: int | None
    skipped_reason: str | None
    failure_stage: str | None
    resolved_at: datetime | None
    started_at: datetime
    completed_at: datetime | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class DeadLetterOut(BaseModel):
    """Dead-letter record summary; no PII/secrets (FR-011)."""

    id: int
    job_name: str
    job_key: str
    client_id: int | None
    args_digest: str
    error_class: str
    error_summary: str | None
    attempts: int
    first_failed_at: datetime
    dead_lettered_at: datetime
    resolved_at: datetime | None

    model_config = {"from_attributes": True}


# ── Cycle endpoints ───────────────────────────────────────────────────────────


@router.get("/clients/{client_id}/watchlists/{watchlist_id}/cycles", response_model=list[CycleOut])
async def list_cycles(
    client_id: int,
    watchlist_id: int,
    limit: int = Query(50, ge=1, le=500),
    target: Client = Depends(get_acting_client_read),
    session: AsyncSession = Depends(get_session),
) -> list[CycleOut]:
    """List cycles for a watchlist (most recent first)."""
    if target.id != client_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CROSS_CLIENT")
    stmt = (
        select(WatchlistCycle)
        .where(
            WatchlistCycle.client_id == client_id,
            WatchlistCycle.watchlist_id == watchlist_id,
        )
        .order_by(WatchlistCycle.started_at.desc())
        .limit(limit)
    )
    cycles = (await session.execute(stmt)).scalars().all()
    return [CycleOut.model_validate(c) for c in cycles]


@router.post(
    "/clients/{client_id}/watchlists/{watchlist_id}/cycles/{cycle_id}/abandon",
    response_model=CycleOut,
)
async def abandon_cycle(
    client_id: int,
    watchlist_id: int,
    cycle_id: int,
    staff: User = Depends(require_staff),
    session: AsyncSession = Depends(get_session),
) -> CycleOut:
    """Operator: abandon a failed cycle to allow rescheduling (FR-018b)."""
    from app.scheduling.service import CycleService

    cycle = await session.get(WatchlistCycle, cycle_id)
    if cycle is None or cycle.client_id != client_id or cycle.watchlist_id != watchlist_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CYCLE_NOT_FOUND")
    try:
        cycle = await CycleService.abandon_cycle(session, cycle_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return CycleOut.model_validate(cycle)


# ── Dead-letter admin endpoints ───────────────────────────────────────────────


@router.get("/admin/dead-letters", response_model=list[DeadLetterOut])
async def list_dead_letters(
    request: Request,
    resolved: bool = Query(False),
    client_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    manager: User = Depends(require_manager),
    session: AsyncSession = Depends(get_session),
) -> list[DeadLetterOut]:
    """Manager-only: list dead-lettered jobs (unresolved by default); platform ops, not admin."""
    stmt = select(DeadLetter).order_by(DeadLetter.dead_lettered_at.desc()).limit(limit)
    if not resolved:
        stmt = stmt.where(DeadLetter.resolved_at.is_(None))
    if client_id is not None:
        stmt = stmt.where(DeadLetter.client_id == client_id)
    rows = (await session.execute(stmt)).scalars().all()
    return [DeadLetterOut.model_validate(r) for r in rows]


@router.post("/admin/dead-letters/{dead_letter_id}/resolve", response_model=DeadLetterOut)
async def resolve_dead_letter(
    dead_letter_id: int,
    manager: User = Depends(require_manager),
    session: AsyncSession = Depends(get_session),
) -> DeadLetterOut:
    """Manager-only: mark a dead-letter record resolved (operator-acknowledged)."""
    from datetime import UTC

    row = await session.get(DeadLetter, dead_letter_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="NOT_FOUND")
    if row.resolved_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="ALREADY_RESOLVED")
    row.resolved_at = datetime.now(UTC)
    await session.flush()

    return DeadLetterOut.model_validate(row)
