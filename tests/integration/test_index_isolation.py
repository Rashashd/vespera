"""Integration test for client isolation in index builds (T044, SC-002, FR-014)."""

import os

import pytest
from sqlalchemy import select

from app.embedding.models import Chunk
from app.embedding.runner import index_build_runner

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires PANTERA_INTEGRATION=1 and docker compose up",
)

_PUBMED_XML = """<?xml version="1.0"?>
<PubmedArticle>
  <Article>
    <ArticleTitle>{title}</ArticleTitle>
    <Abstract><AbstractText>Isolation test content for {title}.</AbstractText></Abstract>
  </Article>
</PubmedArticle>"""


@pytest.mark.asyncio
class TestIndexIsolation:
    """Test that chunks from one client are never visible to another (SC-002, FR-014)."""

    async def test_chunks_client_scoped(
        self, auth_app, make_client, make_watchlist, make_document, mock_modelserver_client
    ) -> None:
        """Chunks belong to the client they were indexed for; cross-client read returns 0."""
        session_factory = auth_app.state.session_factory

        client_a = await make_client()
        client_b = await make_client()
        wl_a = await make_watchlist(client_id=client_a.id)
        wl_b = await make_watchlist(client_id=client_b.id)

        await make_document(
            client_id=client_a.id,
            source_name="pubmed",
            source_payload=_PUBMED_XML.format(title="Doc A"),
            title="Doc A",
            watchlist_id=wl_a.id,
        )
        doc_b = await make_document(
            client_id=client_b.id,
            source_name="pubmed",
            source_payload=_PUBMED_XML.format(title="Doc B"),
            title="Doc B",
            watchlist_id=wl_b.id,
        )

        await index_build_runner(
            session_factory=session_factory,
            client_id=client_a.id,
            modelserver_client=mock_modelserver_client,
        )
        await index_build_runner(
            session_factory=session_factory,
            client_id=client_b.id,
            modelserver_client=mock_modelserver_client,
        )

        async with session_factory() as s:
            chunks_a = (
                (await s.execute(select(Chunk).where(Chunk.client_id == client_a.id)))
                .scalars()
                .all()
            )
            chunks_b = (
                (await s.execute(select(Chunk).where(Chunk.client_id == client_b.id)))
                .scalars()
                .all()
            )
            cross_chunks = (
                (
                    await s.execute(
                        select(Chunk).where(
                            (Chunk.client_id == client_a.id) & (Chunk.document_id == doc_b.id)
                        )
                    )
                )
                .scalars()
                .all()
            )

        assert len(chunks_a) > 0, "Client A should have chunks"
        assert len(chunks_b) > 0, "Client B should have chunks"
        for chunk in chunks_a:
            assert chunk.client_id == client_a.id, "Chunk should belong to client A"
        for chunk in chunks_b:
            assert chunk.client_id == client_b.id, "Chunk should belong to client B"
        assert (
            len(cross_chunks) == 0
        ), f"Cross-client read should return 0 (got {len(cross_chunks)})"
