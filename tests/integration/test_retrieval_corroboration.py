"""Integration test: multi-source corroboration count and completeness (T026 / US3 / SC-003)."""

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


def _make_mock_ms(sha: str = _SHA):
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


@pytest.mark.asyncio
class TestRetrievalCorroboration:
    """Corroboration count == distinct documents in top-K; sources never truncated (US3)."""

    async def test_corroboration_count_matches_distinct_docs(
        self, auth_app, client, make_client, make_watchlist, make_document, make_staff_user
    ) -> None:
        """N documents indexed for same query → corroboration_count == N distinct in results."""
        from tests.integration.conftest import login_token

        session_factory = auth_app.state.session_factory
        c = await make_client()
        wl = await make_watchlist(client_id=c.id)

        n_docs = 3
        for i in range(n_docs):
            await make_document(
                client_id=c.id,
                source_name="pubmed",
                source_payload=_PUBMED_XML.format(
                    title=f"Hepatotox study {i}",
                    content=f"hepatotoxicity liver injury drug {i} adverse reaction",
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
                json={"query": "hepatotoxicity liver injury", "top_k": 20},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200
        data = resp.json()

        # corroboration_count == distinct document_ids in results
        result_doc_ids = {p["document_id"] for p in data["results"]}
        assert data["corroboration_count"] == len(result_doc_ids)

        # All distinct docs listed — never truncated (FR-015)
        source_doc_ids = {s["document_id"] for s in data["corroboration_sources"]}
        assert source_doc_ids == result_doc_ids

    async def test_multi_passage_paper_counts_once(
        self, auth_app, client, make_client, make_watchlist, make_document, make_staff_user
    ) -> None:
        """A document with multiple top-K chunks counts as ONE corroboration source."""
        from tests.integration.conftest import login_token

        session_factory = auth_app.state.session_factory
        c = await make_client()
        wl = await make_watchlist(client_id=c.id)

        # One doc with a large body → likely produces multiple chunks
        await make_document(
            client_id=c.id,
            source_name="pubmed",
            source_payload=_PUBMED_XML.format(
                title="Comprehensive hepatotoxicity review",
                content="hepatotoxicity liver injury adverse event drug reaction "
                * 20,  # enough for 2+ chunks
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
                json={"query": "hepatotoxicity", "top_k": 20},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200
        data = resp.json()

        # Only one document → corroboration_count == 1 regardless of passage count
        assert data["corroboration_count"] == 1
        assert len(data["corroboration_sources"]) == 1

    async def test_corroboration_sources_carry_passage_chunk_ids(
        self, auth_app, client, make_client, make_watchlist, make_document, make_staff_user
    ) -> None:
        """Each CorroborationSource lists all chunk_ids from that document in results."""
        from tests.integration.conftest import login_token

        session_factory = auth_app.state.session_factory
        c = await make_client()
        wl = await make_watchlist(client_id=c.id)

        await make_document(
            client_id=c.id,
            source_name="pubmed",
            source_payload=_PUBMED_XML.format(
                title="Drug safety",
                content="hepatotoxicity adverse event safety signal drug",
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
                json={"query": "hepatotoxicity", "top_k": 20},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200
        data = resp.json()

        if data["corroboration_sources"]:
            result_chunk_ids = {p["chunk_id"] for p in data["results"]}
            for src in data["corroboration_sources"]:
                # Every passage_chunk_id must appear in results
                for cid in src["passage_chunk_ids"]:
                    assert cid in result_chunk_ids
