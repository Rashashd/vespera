"""FastAPI routes for the RAG retrieval endpoint (POST /clients/{client_id}/search)."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.auth.dependencies import get_acting_client
from app.clients.models import Client
from app.db.rls import set_rls_context
from app.infra.modelserver_client import ModelserverClient, ModelserverError
from app.rag.query_embed import EmbedderVersionMismatch, query_hash
from app.rag.schemas import RetrieveRequest, RetrieveResponse

router = APIRouter(prefix="/clients/{client_id}", tags=["rag"])
_log = structlog.get_logger(__name__)


@router.post(
    "/search",
    response_model=RetrieveResponse,
    status_code=status.HTTP_200_OK,
)
async def search(
    request: Request,
    body: RetrieveRequest,
    target: Client = Depends(get_acting_client),
) -> RetrieveResponse:
    """Retrieve ranked evidence passages from a client's chunk index (FR-021).

    Any authenticated staff (or authorized client-user) may call this — no require_admin.
    Suspended clients are refused by get_acting_client (400 CLIENT_SUSPENDED).
    """
    from app.rag import service as rag_service

    session_factory = request.app.state.session_factory
    settings = request.app.state.settings
    redis = getattr(request.app.state, "redis", None)
    app_state = request.app.state

    qhash = query_hash(body.query)
    log = _log.bind(client_id=target.id, query_hash=qhash[:12])

    try:
        async with ModelserverClient.from_settings(settings) as ms_client:
            async with session_factory() as session:
                await set_rls_context(session, client_id=target.id, is_staff=False)
                result = await rag_service.retrieve(
                    session=session,
                    redis=redis,
                    ms_client=ms_client,
                    client=target,
                    req=body,
                    app_state=app_state,
                )
        log.info("rag.search.ok", result_count=len(result.results))
        return result

    except EmbedderVersionMismatch:
        log.warning("rag.embedder_version_mismatch")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="EMBEDDER_VERSION_MISMATCH",
        ) from None
    except ModelserverError as exc:
        log.error("rag.modelserver_error", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="MODELSERVER_UNAVAILABLE",
        ) from exc
