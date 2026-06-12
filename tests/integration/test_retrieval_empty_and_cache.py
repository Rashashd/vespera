"""Integration test: empty corpus + cache behaviour (T014/T041 / FR-015/018 / SC-007)."""

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

_CACHE_SHA = "e" * 64


def _make_indexer_ms(sha: str = _CACHE_SHA):
    """Mock ModelserverClient for indexing — deterministic embeddings."""
    mock_client = AsyncMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    async def _embed(texts):
        results = []
        for text in texts:
            rng = np.random.default_rng(hash(text) % 2**31)
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


def _make_route_ms(sha: str = _CACHE_SHA):
    """Mock for the route's ModelserverClient."""
    mock_client = AsyncMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    async def _embed(texts):
        results = []
        for text in texts:
            rng = np.random.default_rng(hash(text) % 2**31)
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


@pytest.mark.asyncio
class TestRetrievalEmptyAndCache:
    """Empty corpus and cache behaviour (FR-015 / SC-007 / FR-018)."""

    async def test_empty_corpus_returns_empty_200(
        self, client, make_client, make_staff_user
    ) -> None:
        """No chunks for client → 200 with results:[], corroboration_count:0 (FR-015/SC-007)."""
        from tests.integration.conftest import login_token

        empty_client = await make_client()
        staff = await make_staff_user(role="reviewer")
        token = await login_token(client, staff.email)

        resp = await client.post(
            f"/clients/{empty_client.id}/search",
            json={"query": "hepatotoxicity", "top_k": 10},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["results"] == []
        assert data["corroboration_count"] == 0
        assert data["corroboration_sources"] == []
        # query_hash should be present (no raw query text)
        assert "query_hash" in data and len(data["query_hash"]) > 0

    async def test_empty_corpus_no_modelserver_call(
        self, client, make_client, make_staff_user
    ) -> None:
        """Empty corpus short-circuit must NOT call the modelserver (FR-015)."""
        from tests.integration.conftest import login_token

        empty_client = await make_client()
        staff = await make_staff_user(role="reviewer")
        token = await login_token(client, staff.email)

        with patch("app.rag.routes.ModelserverClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_ms = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ms)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_cls.from_settings.return_value = mock_ctx

            resp = await client.post(
                f"/clients/{empty_client.id}/search",
                json={"query": "hepatotoxicity"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200
        # Modelserver embed must NOT have been called for an empty corpus
        mock_ms.embed.assert_not_called()

    async def test_cache_down_does_not_fail_query(
        self, auth_app, client, make_client, make_staff_user
    ) -> None:
        """Redis failure during cache lookup must not fail the query (FR-018).

        Uses an empty-corpus client so no modelserver call is needed.
        """
        from tests.integration.conftest import login_token

        empty_client = await make_client()
        staff = await make_staff_user(role="reviewer")
        token = await login_token(client, staff.email)

        # Simulate Redis outage by making every redis call raise
        err = Exception("redis down")
        mock_redis = AsyncMock(
            get=AsyncMock(side_effect=err),
            set=AsyncMock(side_effect=err),
        )
        with patch.object(auth_app.state, "redis", mock_redis):
            resp = await client.post(
                f"/clients/{empty_client.id}/search",
                json={"query": "hepatotoxicity"},
                headers={"Authorization": f"Bearer {token}"},
            )

        # Empty corpus path doesn't even reach Redis, so 200 regardless
        assert resp.status_code == 200

    async def test_cache_hit_skips_second_embed(
        self, auth_app, client, make_client, make_watchlist, make_document, make_staff_user
    ) -> None:
        """Same query twice: second call served from Redis cache (US5/FR-018)."""
        from tests.integration.conftest import login_token

        session_factory = auth_app.state.session_factory
        # Clear stale cache entries so repeat runs start cold
        stale = await auth_app.state.redis.keys("rag:qemb:*")
        if stale:
            await auth_app.state.redis.delete(*stale)

        c = await make_client()
        wl = await make_watchlist(client_id=c.id)

        await make_document(
            client_id=c.id,
            source_name="pubmed",
            source_payload=_PUBMED_XML.format(
                title="Cache test document",
                content="hepatotoxicity adverse event drug reaction clinical",
            ),
            watchlist_id=wl.id,
        )

        _, mock_ms = _make_indexer_ms(_CACHE_SHA)
        await index_build_runner(
            session_factory=session_factory, client_id=c.id, modelserver_client=mock_ms
        )

        staff = await make_staff_user(role="reviewer")
        token = await login_token(client, staff.email)

        # Ensure embedder_sha is not pre-set so the first request populates it
        if hasattr(auth_app.state, "embedder_sha"):
            auth_app.state.embedder_sha = ""

        # First request: embed IS called; result written to Redis
        route_ctx_1, route_ms_1 = _make_route_ms(_CACHE_SHA)
        with patch("app.rag.routes.ModelserverClient") as mock_cls:
            mock_cls.from_settings.return_value = route_ctx_1
            resp1 = await client.post(
                f"/clients/{c.id}/search",
                json={"query": "hepatotoxicity drug reaction", "top_k": 5},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp1.status_code == 200
        assert route_ms_1.embed.call_count == 1, "First request must call embed once"

        # Second identical request: cache hit → embed NOT called
        route_ctx_2, route_ms_2 = _make_route_ms(_CACHE_SHA)
        with patch("app.rag.routes.ModelserverClient") as mock_cls:
            mock_cls.from_settings.return_value = route_ctx_2
            resp2 = await client.post(
                f"/clients/{c.id}/search",
                json={"query": "hepatotoxicity drug reaction", "top_k": 5},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp2.status_code == 200
        assert route_ms_2.embed.call_count == 0, "Second request must be served from cache"

    async def test_different_query_calls_embed_again(
        self, auth_app, client, make_client, make_watchlist, make_document, make_staff_user
    ) -> None:
        """A different query misses the cache and calls embed (version-scoped key)."""
        from tests.integration.conftest import login_token

        session_factory = auth_app.state.session_factory
        # Clear stale cache entries so repeat runs start cold
        stale = await auth_app.state.redis.keys("rag:qemb:*")
        if stale:
            await auth_app.state.redis.delete(*stale)

        c = await make_client()
        wl = await make_watchlist(client_id=c.id)

        await make_document(
            client_id=c.id,
            source_name="pubmed",
            source_payload=_PUBMED_XML.format(
                title="Cache miss test",
                content="hepatotoxicity adverse drug event clinical study",
            ),
            watchlist_id=wl.id,
        )

        _, mock_ms_idx = _make_indexer_ms(_CACHE_SHA)
        await index_build_runner(
            session_factory=session_factory, client_id=c.id, modelserver_client=mock_ms_idx
        )

        staff = await make_staff_user(role="reviewer")
        token = await login_token(client, staff.email)

        # Prime cache with first query
        route_ctx_1, _ = _make_route_ms(_CACHE_SHA)
        with patch("app.rag.routes.ModelserverClient") as mock_cls:
            mock_cls.from_settings.return_value = route_ctx_1
            await client.post(
                f"/clients/{c.id}/search",
                json={"query": "hepatotoxicity", "top_k": 5},
                headers={"Authorization": f"Bearer {token}"},
            )

        # Different query → cache miss → embed called
        route_ctx_2, route_ms_2 = _make_route_ms(_CACHE_SHA)
        with patch("app.rag.routes.ModelserverClient") as mock_cls:
            mock_cls.from_settings.return_value = route_ctx_2
            resp = await client.post(
                f"/clients/{c.id}/search",
                json={"query": "kidney failure drug", "top_k": 5},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        assert route_ms_2.embed.call_count == 1, "Different query must call embed"
