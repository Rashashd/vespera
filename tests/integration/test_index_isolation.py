"""Integration test for client isolation in index builds (T044, SC-002, FR-014)."""

import os

import pytest
from sqlalchemy import select

from app.embedding.models import Chunk
from app.embedding.runner import index_build_runner
from tests.conftest import make_client, make_document, make_watchlist

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires PANTERA_INTEGRATION=1 and docker compose up",
)


@pytest.mark.asyncio
class TestIndexIsolation:
    """Test that chunks from one client are never visible to another (SC-002, FR-014)."""

    async def test_chunks_client_scoped(
        self, async_session, mock_modelserver_client
    ) -> None:
        """Chunks belong to the client they were indexed for; cross-client read returns 0."""
        # Setup: two clients with documents
        client_a = await make_client(async_session)
        client_b = await make_client(async_session)

        wl_a = await make_watchlist(async_session, client_id=client_a.id)
        wl_b = await make_watchlist(async_session, client_id=client_b.id)

        doc_a = await make_document(async_session, client_id=client_a.id, title="Doc A")
        doc_b = await make_document(async_session, client_id=client_b.id, title="Doc B")

        # Link to watchlists
        from app.ingestion.models import DocumentWatchlist
        la = DocumentWatchlist(document_id=doc_a.id, watchlist_id=wl_a.id)
        lb = DocumentWatchlist(document_id=doc_b.id, watchlist_id=wl_b.id)
        async_session.add(la)
        async_session.add(lb)
        await async_session.flush()

        # Index both clients
        await index_build_runner(
            session_factory=lambda: async_session,
            client_id=client_a.id,
            modelserver_client=mock_modelserver_client,
        )
        await index_build_runner(
            session_factory=lambda: async_session,
            client_id=client_b.id,
            modelserver_client=mock_modelserver_client,
        )

        # Query client A's chunks (should only see A's chunks)
        stmt_a = select(Chunk).where(Chunk.client_id == client_a.id)
        chunks_a = (await async_session.execute(stmt_a)).scalars().all()

        # Query client B's chunks (should only see B's chunks)
        stmt_b = select(Chunk).where(Chunk.client_id == client_b.id)
        chunks_b = (await async_session.execute(stmt_b)).scalars().all()

        # Verify isolation
        assert len(chunks_a) > 0, "Client A should have chunks"
        assert len(chunks_b) > 0, "Client B should have chunks"

        # Verify no cross-client leakage
        for chunk in chunks_a:
            assert chunk.client_id == client_a.id, "Chunk should belong to client A"
            assert chunk.client_id != client_b.id, "Chunk should not belong to client B"

        for chunk in chunks_b:
            assert chunk.client_id == client_b.id, "Chunk should belong to client B"
            assert chunk.client_id != client_a.id, "Chunk should not belong to client A"

        # Cross-client read attempt (client A trying to read B's chunks)
        stmt_cross = select(Chunk).where(
            (Chunk.client_id == client_a.id) & (Chunk.document_id == doc_b.id)
        )
        cross_chunks = (await async_session.execute(stmt_cross)).scalars().all()

        assert len(cross_chunks) == 0, (
            f"Cross-client read should return 0 (got {len(cross_chunks)})"
        )
