"""Ingestion trigger + run-status endpoints (contracts/ingestion-runs.md)."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import current_active_user, require_admin
from app.auth.models import User
from app.clients import service as client_service
from app.core.dependencies import get_session
from app.domain.events import IngestionRunTriggered
from app.ingestion import service as ingest_service
from app.ingestion.runner import run_ingestion
from app.ingestion.schemas import IngestionRunOut

router = APIRouter(tags=["ingestion"])
_log = structlog.get_logger(__name__)


@router.post(
    "/watchlists/{watchlist_id}/ingest",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=IngestionRunOut,
)
async def trigger_ingestion(
    watchlist_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> IngestionRunOut:
    """Trigger an ingestion run for an active, non-empty watchlist (admin-only, FR-008, US1)."""
    watchlist = await client_service.get_watchlist(session, admin.client_id, watchlist_id)
    if watchlist is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WATCHLIST_NOT_FOUND")
    if not watchlist.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="WATCHLIST_INACTIVE")
    if not watchlist.items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="WATCHLIST_EMPTY")

    run = await ingest_service.create_run(
        session,
        client_id=admin.client_id,
        watchlist_id=watchlist_id,
        triggered_by_user_id=admin.id,
    )
    await request.app.state.dispatcher.dispatch(
        IngestionRunTriggered(
            actor_id=admin.id,
            actor_type="human",
            client_id=admin.client_id,
            run_id=run.id,
            watchlist_id=watchlist_id,
        ),
        session,
    )

    settings = request.app.state.settings
    session_factory = request.app.state.session_factory

    # Copy items out of the ORM session so the background task doesn't use a closed session.
    items_snapshot = list(watchlist.items)

    background_tasks.add_task(
        run_ingestion,
        run_id=run.id,
        client_id=admin.client_id,
        watchlist_id=watchlist_id,
        watchlist_items=items_snapshot,
        session_factory=session_factory,
        initial_lookback_days=settings.ingestion_initial_lookback_days,
        per_source_cap=settings.ingestion_per_source_cap,
    )

    _log.info(
        "ingestion.triggered",
        run_id=run.id,
        client_id=admin.client_id,
        watchlist_id=watchlist_id,
    )
    return IngestionRunOut.from_orm(run)


@router.get(
    "/watchlists/{watchlist_id}/ingestion-runs",
    response_model=list[IngestionRunOut],
)
async def list_ingestion_runs(
    watchlist_id: int,
    limit: int = 50,
    offset: int = 0,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> list[IngestionRunOut]:
    """List runs for a watchlist, newest first (admin + reviewer, FR-008)."""
    watchlist = await client_service.get_watchlist(session, user.client_id, watchlist_id)
    if watchlist is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WATCHLIST_NOT_FOUND")
    runs = await ingest_service.list_runs(
        session, user.client_id, watchlist_id, limit=limit, offset=offset
    )
    return [IngestionRunOut.from_orm(r) for r in runs]


@router.get("/ingestion-runs/{run_id}", response_model=IngestionRunOut)
async def get_ingestion_run(
    run_id: int,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> IngestionRunOut:
    """Run detail with per-source outcomes; cross-tenant → 404 (SC-007, US5-2)."""
    run = await ingest_service.get_run(session, user.client_id, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="RUN_NOT_FOUND")
    return IngestionRunOut.from_orm(run)
