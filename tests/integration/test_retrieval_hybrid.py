"""Integration test: hybrid (dense+lexical) retrieval recall (T021 / US2)."""

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

_SHA = "b" * 64


def _make_mock_ms(sha: str = _SHA, *, embed_fn=None):
    """Build a mock ModelserverClient context manager."""
    mock_client = AsyncMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    async def _default_embed(texts):
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

    fn = embed_fn or _default_embed
    mock_client.embed = AsyncMock(side_effect=fn)
    mock_client.embed_chunked = AsyncMock(side_effect=fn)
    return mock_ctx, mock_client


@pytest.mark.asyncio
class TestRetrievalHybrid:
    """Dense+lexical fusion surfaces matches that each leg alone may miss (US2)."""

    async def test_lexical_only_match_surfaces_in_fused(
        self, auth_app, client, make_client, make_watchlist, make_document, make_staff_user
    ) -> None:
        """A document with rare-term match surfaces even if its semantic embedding is distant."""
        from tests.integration.conftest import login_token

        session_factory = auth_app.state.session_factory
        c = await make_client()
        wl = await make_watchlist(client_id=c.id)

        # This document contains rare term 'xanthogranuloma' → lexical match
        await make_document(
            client_id=c.id,
            source_name="pubmed",
            source_payload=_PUBMED_XML.format(
                title="Xanthogranuloma drug report",
                content="xanthogranuloma associated with medication induced reaction",
            ),
            watchlist_id=wl.id,
        )
        # A semantically relevant but lexically unrelated doc
        await make_document(
            client_id=c.id,
            source_name="pubmed",
            source_payload=_PUBMED_XML.format(
                title="Liver toxicity",
                content="hepatotoxicity and liver damage after drug administration",
            ),
            watchlist_id=wl.id,
        )

        _, mock_ms = _make_mock_ms(_SHA)
        await index_build_runner(
            session_factory=session_factory, client_id=c.id, modelserver_client=mock_ms
        )

        staff = await make_staff_user(role="reviewer")
        token = await login_token(client, staff.email)

        mock_ctx, _ = _make_mock_ms(_SHA)
        with patch("app.rag.routes.ModelserverClient") as mock_cls:
            mock_cls.from_settings.return_value = mock_ctx
            resp = await client.post(
                f"/clients/{c.id}/search",
                json={"query": "xanthogranuloma", "top_k": 10},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200
        data = resp.json()
        # At least one chunk's text should contain the rare term
        texts = [p.get("text", "") for p in data["results"]]
        assert any(
            "xanthogranuloma" in t.lower() for t in texts
        ), f"Expected xanthogranuloma chunk in results, got texts: {[t[:60] for t in texts]}"

    async def test_fused_results_are_deduplicated(
        self, auth_app, client, make_client, make_watchlist, make_document, make_staff_user
    ) -> None:
        """No chunk_id appears more than once in fused results (de-duplication contract)."""
        from tests.integration.conftest import login_token

        session_factory = auth_app.state.session_factory
        c = await make_client()
        wl = await make_watchlist(client_id=c.id)

        await make_document(
            client_id=c.id,
            source_name="pubmed",
            source_payload=_PUBMED_XML.format(
                title="Adverse event report",
                content="hepatotoxicity adverse event drug reaction patient",
            ),
            watchlist_id=wl.id,
        )

        _, mock_ms = _make_mock_ms(_SHA)
        await index_build_runner(
            session_factory=session_factory, client_id=c.id, modelserver_client=mock_ms
        )

        staff = await make_staff_user(role="reviewer")
        token = await login_token(client, staff.email)

        mock_ctx, _ = _make_mock_ms(_SHA)
        with patch("app.rag.routes.ModelserverClient") as mock_cls:
            mock_cls.from_settings.return_value = mock_ctx
            resp = await client.post(
                f"/clients/{c.id}/search",
                json={"query": "hepatotoxicity adverse event", "top_k": 20},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200
        chunk_ids = [p["chunk_id"] for p in resp.json()["results"]]
        assert len(chunk_ids) == len(set(chunk_ids)), "Duplicate chunk_ids in fused results"

    async def test_rank_is_contiguous_1based(
        self, auth_app, client, make_client, make_watchlist, make_document, make_staff_user
    ) -> None:
        """Returned passages have contiguous 1-based rank (FR-010)."""
        from tests.integration.conftest import login_token

        session_factory = auth_app.state.session_factory
        c = await make_client()
        wl = await make_watchlist(client_id=c.id)

        for i in range(3):
            await make_document(
                client_id=c.id,
                source_name="pubmed",
                source_payload=_PUBMED_XML.format(
                    title=f"Drug report {i}", content=f"adverse event drug toxicity report {i}"
                ),
                watchlist_id=wl.id,
            )

        _, mock_ms = _make_mock_ms(_SHA)
        await index_build_runner(
            session_factory=session_factory, client_id=c.id, modelserver_client=mock_ms
        )

        staff = await make_staff_user(role="reviewer")
        token = await login_token(client, staff.email)

        mock_ctx, _ = _make_mock_ms(_SHA)
        with patch("app.rag.routes.ModelserverClient") as mock_cls:
            mock_cls.from_settings.return_value = mock_ctx
            resp = await client.post(
                f"/clients/{c.id}/search",
                json={"query": "drug toxicity", "top_k": 10},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200
        ranks = [p["rank"] for p in resp.json()["results"]]
        assert ranks == list(range(1, len(ranks) + 1)), f"Non-contiguous ranks: {ranks}"
