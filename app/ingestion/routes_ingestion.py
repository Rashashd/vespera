"""Ingestion trigger + run-status endpoints (contracts/ingestion-runs.md)."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_acting_client, get_acting_client_read, require_admin
from app.auth.models import User
from app.clients import service as client_service
from app.clients.models import Client
from app.core.dependencies import get_session
from app.domain.events import IngestionRunTriggered
from app.ingestion import service as ingest_service
from app.ingestion.runner import run_ingestion
from app.ingestion.schemas import IngestionRunOut

router = APIRouter(prefix="/clients/{client_id}", tags=["ingestion"])
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
    target: Client = Depends(get_acting_client),
    admin: User = Depends(require_admin),
) -> IngestionRunOut:
    """Trigger an ingestion run for an active, non-empty watchlist (admin-only, FR-008, FR-006).

    Session is managed explicitly here (not via get_session dependency) so the transaction
    commits before BackgroundTasks runs — FastAPI runs background tasks after the response is
    sent but before generator-dependency cleanup, which would otherwise leave run_id uncommitted
    when the runner opens its own session.
    """
    session_factory = request.app.state.session_factory
    settings = request.app.state.settings
    dispatcher = request.app.state.dispatcher

    async with session_factory() as session:
        async with session.begin():
            watchlist = await client_service.get_watchlist(session, target.id, watchlist_id)
            if watchlist is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="WATCHLIST_NOT_FOUND"
                )
            if not watchlist.is_active:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="WATCHLIST_INACTIVE"
                )
            if not watchlist.items:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="WATCHLIST_EMPTY"
                )

            run = await ingest_service.create_run(
                session,
                client_id=target.id,
                watchlist_id=watchlist_id,
                triggered_by_user_id=admin.id,
            )
            await dispatcher.dispatch(
                IngestionRunTriggered(
                    actor_id=admin.id,
                    actor_type="human",
                    client_id=target.id,
                    run_id=run.id,
                    watchlist_id=watchlist_id,
                ),
                session,
            )
            # Snapshot items before the session closes.
            items_snapshot = list(watchlist.items)
            run_id = run.id
            run_out = IngestionRunOut.from_orm(run)
        # Transaction commits here — run_id is now visible to the runner's sessions.

    background_tasks.add_task(
        run_ingestion,
        run_id=run_id,
        client_id=target.id,
        watchlist_id=watchlist_id,
        watchlist_items=items_snapshot,
        session_factory=session_factory,
        initial_lookback_days=settings.ingestion_initial_lookback_days,
        per_source_cap=settings.ingestion_per_source_cap,
    )

    _log.info(
        "ingestion.triggered",
        run_id=run_id,
        client_id=target.id,
        watchlist_id=watchlist_id,
    )
    return run_out


@router.get(
    "/watchlists/{watchlist_id}/ingestion-runs",
    response_model=list[IngestionRunOut],
)
async def list_ingestion_runs(
    watchlist_id: int,
    limit: int = 50,
    offset: int = 0,
    target: Client = Depends(get_acting_client_read),
    session: AsyncSession = Depends(get_session),
) -> list[IngestionRunOut]:
    """List runs for a watchlist, newest first (FR-008)."""
    watchlist = await client_service.get_watchlist(session, target.id, watchlist_id)
    if watchlist is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WATCHLIST_NOT_FOUND")
    runs = await ingest_service.list_runs(
        session, target.id, watchlist_id, limit=limit, offset=offset
    )
    return [IngestionRunOut.from_orm(r) for r in runs]


@router.get("/ingestion-runs/{run_id}", response_model=IngestionRunOut)
async def get_ingestion_run(
    run_id: int,
    target: Client = Depends(get_acting_client_read),
    session: AsyncSession = Depends(get_session),
) -> IngestionRunOut:
    """Run detail with per-source outcomes; cross-tenant → 404 (SC-007, US5-2)."""
    run = await ingest_service.get_run(session, target.id, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="RUN_NOT_FOUND")
    return IngestionRunOut.from_orm(run)
