"""FastAPI routes for index build trigger and status endpoints."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select

from app.auth.dependencies import get_acting_client, get_acting_client_read, require_admin
from app.auth.models import User
from app.clients.models import Client
from app.db.rls import set_rls_context
from app.domain.events import IndexBuildTriggered
from app.embedding import service as embedding_service
from app.embedding.models import DocumentIndexState
from app.embedding.schemas import DocumentIndexStateOut, IndexBuildRunOut
from app.jobs.enqueue import enqueue

router = APIRouter(prefix="/clients/{client_id}", tags=["embedding"])
_log = structlog.get_logger(__name__)


@router.post(
    "/index",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=IndexBuildRunOut,
)
async def trigger_index_build(
    request: Request,
    target: Client = Depends(get_acting_client),
    admin: User = Depends(require_admin),
) -> IndexBuildRunOut:
    """Trigger a client-wide manual index build (manager/admin-only, FR-017/FR-026/FR-027).

    watchlist_id=None → client-wide manual build (G2: distinct from cycle-scoped builds).
    """
    session_factory = request.app.state.session_factory
    dispatcher = request.app.state.dispatcher

    async with session_factory() as session:
        async with session.begin():
            await set_rls_context(session, client_id=target.id, is_staff=False)
            run, is_new_run = await embedding_service.IndexBuildService.create_run(
                session,
                client_id=target.id,
                triggered_by_user_id=admin.id,
            )
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

    if is_new_run:
        await enqueue(
            "task_index_build",
            job_id=f"index:{target.id}:manual:{run_id}",
            app_state=request.app.state,
            client_id=target.id,
            watchlist_id=None,  # client-wide manual build (G2)
        )

    return IndexBuildRunOut.model_validate(run)


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
        await set_rls_context(session, client_id=target.id, is_staff=False)
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
        await set_rls_context(session, client_id=target.id, is_staff=False)
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
        await set_rls_context(session, client_id=target.id, is_staff=False)
        query = select(DocumentIndexState).where(DocumentIndexState.client_id == target.id)

        if status_filter:
            query = query.where(DocumentIndexState.status == status_filter)

        query = query.order_by(DocumentIndexState.updated_at.desc()).limit(limit).offset(offset)

        states = (await session.execute(query)).scalars().all()
        return [DocumentIndexStateOut.model_validate(state) for state in states]
