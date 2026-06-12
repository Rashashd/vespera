"""Rerank fused candidates via the modelserver cross-encoder (US4/FR-008)."""

from __future__ import annotations

from app.infra.modelserver_client import ModelserverClient


async def rerank_candidates(
    ms_client: ModelserverClient,
    query: str,
    candidates: list,
    top_k: int,
) -> list:
    """Call /rerank on fused candidates, sort by score desc + id tie-break, take top_k.

    candidates: list of objects with .chunk_id (int) and .text (str), in fused-score order.
    Returns a sub-list of up to top_k candidates reordered by cross-encoder score.
    """
    if not candidates:
        return []

    passages = [c.text for c in candidates]
    results = await ms_client.rerank_chunked(query, passages)

    # Zip scores back by index (input order preserved by /rerank contract)
    scored = [(results[i]["score"], candidates[i]) for i in range(len(candidates))]

    # Sort desc by score; use chunk_id as deterministic tie-break (asc)
    scored.sort(key=lambda x: (-x[0], x[1].chunk_id))

    return [c for _, c in scored[:top_k]]
