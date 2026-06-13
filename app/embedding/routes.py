"""FastAPI routes for index build trigger and status endpoints."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy import select

from app.auth.dependencies import get_acting_client, get_acting_client_read, require_admin
from app.auth.models import User
from app.clients.models import Client
from app.domain.events import IndexBuildTriggered
from app.embedding import service as embedding_service
from app.embedding.models import DocumentIndexState
from app.embedding.runner import index_build_runner
from app.embedding.schemas import DocumentIndexStateOut, IndexBuildRunOut
from app.infra.modelserver_client import ModelserverClient

router = APIRouter(prefix="/clients/{client_id}", tags=["embedding"])
_log = structlog.get_logger(__name__)


@router.post(
    "/index",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=IndexBuildRunOut,
)
async def trigger_index_build(
    request: Request,
    background_tasks: BackgroundTasks,
    target: Client = Depends(get_acting_client),
    admin: User = Depends(require_admin),
) -> IndexBuildRunOut:
    """Trigger an index build for a client's documents (manager/admin-only, FR-017/FR-026/FR-027).

    Session is managed explicitly here so the transaction commits before BackgroundTasks runs.
    """
    session_factory = request.app.state.session_factory
    settings = request.app.state.settings
    dispatcher = request.app.state.dispatcher

    is_new_run = False
    async with session_factory() as session:
        async with session.begin():
            # Create or get in-flight run (FR-026: one per client at a time)
            run, is_new_run = await embedding_service.IndexBuildService.create_run(
                session,
                client_id=target.id,
                triggered_by_user_id=admin.id,
            )

            # Dispatch event for audit (Constitution V: human actor tracked)
            await dispatcher.dispatch(
                IndexBuildTriggered(
                    actor_id=admin.id,
                    actor_type="human",
                    client_id=target.id,
                    run_id=run.id,
                ),
                session,
            )

            run_id = run.id

    # Schedule runner in background ONLY for new runs (H3 fix)
    if is_new_run:
        background_tasks.add_task(
            _run_index_build_background,
            session_factory=session_factory,
            client_id=target.id,
            run_id=run_id,
            settings=settings,
            dispatcher=dispatcher,
            app_state=request.app.state,
        )

    return IndexBuildRunOut.model_validate(run)


async def _run_index_build_background(
    session_factory,
    client_id: int,
    run_id: int,
    settings,
    dispatcher=None,
    app_state=None,
) -> None:
    """Background task runner (decoupled from request cycle)."""
    try:
        async with ModelserverClient.from_settings(settings) as modelserver_client:
            await index_build_runner(
                session_factory=session_factory,
                client_id=client_id,
                modelserver_client=modelserver_client,
                dispatcher=dispatcher,
                app_state=app_state,
            )
    except Exception as e:
        _log.error(
            "Index build background task failed",
            client_id=client_id,
            run_id=run_id,
            error=str(e),
            exc_info=True,
        )


@router.get(
    "/index-runs",
    response_model=list[IndexBuildRunOut],
)
async def list_index_runs(
    request: Request,
    target: Client = Depends(get_acting_client_read),
    limit: int = Query(50, ge=1, le=1000),
) -> list[IndexBuildRunOut]:
    """List index build runs for a client (most recent first, FR-010)."""
    session_factory = request.app.state.session_factory

    async with session_factory() as session:
        runs = await embedding_service.IndexBuildService.list_runs(
            session, client_id=target.id, limit=limit
        )
        return [IndexBuildRunOut.model_validate(run) for run in runs]


@router.get(
    "/index-runs/{run_id}",
    response_model=IndexBuildRunOut,
)
async def get_index_run(
    request: Request,
    run_id: int,
    target: Client = Depends(get_acting_client_read),
) -> IndexBuildRunOut:
    """Get one index build run (tenant isolation: 404 if not in target client)."""
    session_factory = request.app.state.session_factory

    async with session_factory() as session:
        run = await embedding_service.IndexBuildService.get_run(session, run_id)
        if run is None or run.client_id != target.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="RUN_NOT_FOUND")
        return IndexBuildRunOut.model_validate(run)


@router.get(
    "/index-state",
    response_model=list[DocumentIndexStateOut],
)
async def list_document_index_state(
    request: Request,
    target: Client = Depends(get_acting_client_read),
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> list[DocumentIndexStateOut]:
    """List document index states for a client (observability, FR-010)."""
    session_factory = request.app.state.session_factory

    async with session_factory() as session:
        query = select(DocumentIndexState).where(DocumentIndexState.client_id == target.id)

        if status_filter:
            query = query.where(DocumentIndexState.status == status_filter)

        query = query.order_by(DocumentIndexState.updated_at.desc()).limit(limit).offset(offset)

        states = (await session.execute(query)).scalars().all()
        return [DocumentIndexStateOut.model_validate(state) for state in states]
