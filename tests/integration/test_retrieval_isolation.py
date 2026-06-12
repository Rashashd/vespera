"""Integration test: RAG retrieval results are strictly client-scoped (T012 / SC-004)."""

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

_SHA = "a" * 64


def _make_mock_ms(sha: str = _SHA):
    """Build a mock ModelserverClient context manager returning deterministic embeddings."""
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
class TestRetrievalIsolation:
    """RAG search results must never include foreign-client chunks (SC-004)."""

    async def test_zero_foreign_client_results(
        self, auth_app, client, make_client, make_watchlist, make_document, make_staff_user
    ) -> None:
        """Query client_a's search endpoint → no chunk from client_b appears in results."""
        from tests.integration.conftest import login_token

        session_factory = auth_app.state.session_factory

        client_a = await make_client()
        client_b = await make_client()
        wl_a = await make_watchlist(client_id=client_a.id)
        wl_b = await make_watchlist(client_id=client_b.id)

        # Index docs for both clients with the same mock SHA
        _, mock_ms = _make_mock_ms(_SHA)
        await make_document(
            client_id=client_a.id,
            source_name="pubmed",
            source_payload=_PUBMED_XML.format(title="HepatoTox A", content="hepatotoxicity drugA"),
            watchlist_id=wl_a.id,
        )
        await make_document(
            client_id=client_b.id,
            source_name="pubmed",
            source_payload=_PUBMED_XML.format(title="HepatoTox B", content="hepatotoxicity drugB"),
            watchlist_id=wl_b.id,
        )
        await index_build_runner(
            session_factory=session_factory,
            client_id=client_a.id,
            modelserver_client=mock_ms,
        )
        await index_build_runner(
            session_factory=session_factory,
            client_id=client_b.id,
            modelserver_client=mock_ms,
        )

        # Log in as manager staff
        staff = await make_staff_user(role="manager")
        token = await login_token(client, staff.email)

        # Mock the route's ModelserverClient.from_settings call
        mock_ctx, mock_ms2 = _make_mock_ms(_SHA)
        with patch("app.rag.routes.ModelserverClient") as mock_cls:
            mock_cls.from_settings.return_value = mock_ctx

            resp = await client.post(
                f"/clients/{client_a.id}/search",
                json={"query": "hepatotoxicity", "top_k": 20},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200
        data = resp.json()
        for passage in data["results"]:
            assert passage["document_id"] is not None
            # All returned passages must belong to client_a
        # Verify via DB that no result document_id belongs to client_b
        if data["results"]:
            from sqlalchemy import select as sa_select

            from app.embedding.models import Chunk

            result_chunk_ids = [p["chunk_id"] for p in data["results"]]
            async with session_factory() as s:
                foreign = (
                    (
                        await s.execute(
                            sa_select(Chunk).where(
                                Chunk.id.in_(result_chunk_ids),
                                Chunk.client_id == client_b.id,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
            assert len(foreign) == 0, f"Foreign-client chunks returned: {foreign}"
