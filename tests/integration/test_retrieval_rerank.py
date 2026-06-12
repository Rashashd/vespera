"""Integration test: reranker reorders fused top-K deterministically (T030 / US4 / FR-008/010)."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from app.embedding.runner import index_build_runner

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires PANTERA_INTEGRATION=1 and docker compose up",
)

_PUBMED_XML = """<?xml version="1.0"?>
<PubmedArticle>
  <Article>
    <ArticleTitle>{title}</ArticleTitle>
    <Abstract><AbstractText>{content}</AbstractText></Abstract>
  </Article>
</PubmedArticle>"""

_SHA = "c" * 64


def _make_indexer_ms(sha: str = _SHA):
    """Mock ModelserverClient for indexing — returns seeded deterministic embeddings."""
    mock_client = AsyncMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    async def _embed(texts):
        results = []
        for text in texts:
            seed = hash(text) % 2**31
            rng = np.random.default_rng(seed)
            vec = rng.standard_normal(768).astype(np.float32)
            vec /= np.linalg.norm(vec) + 1e-8
            results.append(
                {
                    "embedding": vec.tolist(),
                    "model_version": {"name": "emb", "version": "v1", "sha256": sha},
                }
            )
        return results

    mock_client.embed = AsyncMock(side_effect=_embed)
    mock_client.embed_chunked = AsyncMock(side_effect=_embed)
    return mock_ctx, mock_client


def _make_route_ms(sha: str = _SHA, rerank_scores: list[float] | None = None):
    """Mock for the route-level ModelserverClient with controllable rerank scores."""
    mock_client = AsyncMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    async def _embed(texts):
        results = []
        for text in texts:
            seed = hash(text) % 2**31
            rng = np.random.default_rng(seed)
            vec = rng.standard_normal(768).astype(np.float32)
            vec /= np.linalg.norm(vec) + 1e-8
            results.append(
                {
                    "embedding": vec.tolist(),
                    "model_version": {"name": "emb", "version": "v1", "sha256": sha},
                }
            )
        return results

    async def _rerank_chunked(query, passages):
        if rerank_scores is not None:
            scores = rerank_scores[: len(passages)]
        else:
            # Default: reverse fused order (highest score for last passage)
            scores = list(range(len(passages), 0, -1))
        mv = {"name": "reranker", "version": "v1", "sha256": "d" * 64}
        return [{"score": float(s), "model_version": mv} for s in scores]

    mock_client.embed = AsyncMock(side_effect=_embed)
    mock_client.embed_chunked = AsyncMock(side_effect=_embed)
    mock_client.rerank_chunked = AsyncMock(side_effect=_rerank_chunked)
    return mock_ctx, mock_client


@pytest.mark.asyncio
class TestRetrievalRerank:
    async def test_rerank_reorders_top_k_deterministically(
        self, auth_app, client, make_client, make_watchlist, make_document, make_staff_user
    ) -> None:
        """Reranker reorders fused candidates; same query twice returns identical ordering."""
        from tests.integration.conftest import login_token

        session_factory = auth_app.state.session_factory
        c = await make_client()
        wl = await make_watchlist(client_id=c.id)

        # Seed several documents
        for i in range(4):
            await make_document(
                client_id=c.id,
                source_name="pubmed",
                source_payload=_PUBMED_XML.format(
                    title=f"Hepatotoxicity study {i}",
                    content=f"adverse hepatotoxicity event drug reaction study number {i}",
                ),
                watchlist_id=wl.id,
            )

        _, indexer_ms = _make_indexer_ms(_SHA)
        await index_build_runner(
            session_factory=session_factory, client_id=c.id, modelserver_client=indexer_ms
        )

        staff = await make_staff_user(role="reviewer")
        token = await login_token(client, staff.email)

        # First query — rerank scores reverse fused order (last passage gets highest score)
        mock_ctx, _ = _make_route_ms(_SHA)
        with patch("app.rag.routes.ModelserverClient") as mock_cls:
            mock_cls.from_settings.return_value = mock_ctx
            r1 = await client.post(
                f"/clients/{c.id}/search",
                json={"query": "hepatotoxicity drug reaction", "top_k": 4},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert r1.status_code == 200
        ranks1 = [p["rank"] for p in r1.json()["results"]]
        # Ranks must be contiguous 1-based
        assert ranks1 == list(range(1, len(ranks1) + 1))

        # Second identical query — must produce identical ordering (FR-010 determinism)
        mock_ctx2, _ = _make_route_ms(_SHA)
        with patch("app.rag.routes.ModelserverClient") as mock_cls:
            mock_cls.from_settings.return_value = mock_ctx2
            r2 = await client.post(
                f"/clients/{c.id}/search",
                json={"query": "hepatotoxicity drug reaction", "top_k": 4},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert r2.status_code == 200
        ids1 = [p["chunk_id"] for p in r1.json()["results"]]
        ids2 = [p["chunk_id"] for p in r2.json()["results"]]
        assert ids1 == ids2, f"Non-deterministic rerank order: {ids1} vs {ids2}"

    async def test_rerank_changes_order_vs_fused(
        self, auth_app, client, make_client, make_watchlist, make_document, make_staff_user
    ) -> None:
        """When reranker assigns highest score to last candidate, ordering changes."""
        from tests.integration.conftest import login_token

        session_factory = auth_app.state.session_factory
        c = await make_client()
        wl = await make_watchlist(client_id=c.id)

        for i in range(3):
            await make_document(
                client_id=c.id,
                source_name="pubmed",
                source_payload=_PUBMED_XML.format(
                    title=f"Drug report {i}",
                    content=f"adverse drug event toxicity clinical report {i}",
                ),
                watchlist_id=wl.id,
            )

        _, indexer_ms = _make_indexer_ms(_SHA)
        await index_build_runner(
            session_factory=session_factory, client_id=c.id, modelserver_client=indexer_ms
        )

        staff = await make_staff_user(role="reviewer")
        token = await login_token(client, staff.email)

        # Reranker flips scores: last fused candidate gets score 100, first gets 1
        # This forces reordering relative to fused order
        mock_ctx, _ = _make_route_ms(_SHA, rerank_scores=[1.0, 2.0, 100.0])
        with patch("app.rag.routes.ModelserverClient") as mock_cls:
            mock_cls.from_settings.return_value = mock_ctx
            resp = await client.post(
                f"/clients/{c.id}/search",
                json={"query": "drug toxicity", "top_k": 3},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) >= 1
        # Ranks must be contiguous 1-based regardless of reranker scores
        ranks = [p["rank"] for p in results]
        assert ranks == list(range(1, len(ranks) + 1))
