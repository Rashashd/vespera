"""Reciprocal Rank Fusion over dense and lexical candidate lists."""

from __future__ import annotations

from typing import Any


def reciprocal_rank_fusion(
    *ranked_lists: list[Any],
    k: int = 60,
) -> list[Any]:
    """Fuse ranked candidate lists using RRF (k=60); tie-break by chunk id asc (FR-007/010).

    Each input list contains row-like objects with an `.id` attribute (or dict key).
    A chunk appearing in multiple legs gets summed contributions.
    Returns a single de-duplicated list ordered by fused_score desc, then id asc.
    """
    scores: dict[int, float] = {}
    rows_by_id: dict[int, Any] = {}

    for ranked in ranked_lists:
        for rank_0, row in enumerate(ranked):
            chunk_id = row.id if hasattr(row, "id") else row[0]
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank_0 + 1)
            rows_by_id[chunk_id] = row

    fused = sorted(
        rows_by_id.values(),
        key=lambda r: (
            -scores[r.id if hasattr(r, "id") else r[0]],
            r.id if hasattr(r, "id") else r[0],
        ),
    )
    return fused
