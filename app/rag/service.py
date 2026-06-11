"""RAG retrieval orchestrator: embed → dense+lexical → fuse → rerank → project+corroborate."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.models import Client
from app.embedding.models import Chunk
from app.infra.modelserver_client import ModelserverClient
from app.rag.query_embed import assert_index_version, get_query_embedding, query_hash
from app.rag.schemas import RetrieveRequest, RetrieveResponse


async def retrieve(
    session: AsyncSession,
    redis: Any,
    ms_client: ModelserverClient,
    client: Client,
    req: RetrieveRequest,
    app_state: Any,
) -> RetrieveResponse:
    """Orchestrate the full RAG pipeline and return ranked, corroborated passages.

    Empty corpus short-circuit: if the client has no chunks, return an empty response
    without calling the modelserver (FR-015/SC-007).
    """
    from app.rag.corroboration import build_corroboration
    from app.rag.retrieval import dense_candidates, project_passages

    # Pre-check: empty corpus → skip embed + return immediately (FR-015/SC-007)
    chunk_count = (
        await session.execute(
            select(func.count()).select_from(Chunk).where(Chunk.client_id == client.id)
        )
    ).scalar_one()

    if chunk_count == 0:
        return RetrieveResponse(
            query_hash=query_hash(req.query),
            embedder_version="",
            results=[],
            corroboration_count=0,
            corroboration_sources=[],
        )

    # Embed query — may raise ModelserverError (route maps to 502)
    vector, embedder_sha = await get_query_embedding(
        redis=redis,
        ms_client=ms_client,
        settings=app_state.settings,
        app_state=app_state,
        query=req.query,
    )

    # Embedder-version guard (FR-004) — raises EmbedderVersionMismatch if mismatch
    await assert_index_version(session, client.id, embedder_sha)

    # Dense-only retrieval (US1; replaced by hybrid in US2)
    n_candidates = min(req.top_k * 5, 50)
    dense = await dense_candidates(
        session=session,
        client_id=client.id,
        qvec=vector,
        n=n_candidates,
        chunk_types=[ct.value for ct in req.chunk_types] if req.chunk_types else None,
        source_reliabilities=(
            [sr.value for sr in req.source_reliabilities] if req.source_reliabilities else None
        ),
        date_from=req.date_from,
        date_to=req.date_to,
    )

    if not dense:
        return RetrieveResponse(
            query_hash=query_hash(req.query),
            embedder_version=embedder_sha,
            results=[],
            corroboration_count=0,
            corroboration_sources=[],
        )

    # Project top_k candidates to full passage objects
    top_candidates = dense[: req.top_k]
    passages = await project_passages(session=session, candidates=top_candidates)

    # Assign rank and placeholder score (US1: no reranker yet; dense rank as proxy)
    for i, p in enumerate(passages):
        p.rank = i + 1
        p.score = float(n_candidates - i)

    # Corroboration
    corr_count, corr_sources = build_corroboration(passages)

    return RetrieveResponse(
        query_hash=query_hash(req.query),
        embedder_version=embedder_sha,
        results=passages[: req.top_k],
        corroboration_count=corr_count,
        corroboration_sources=corr_sources,
    )
