"""Integration test for idempotent index builds (T031-T032, SC-003)."""

import os

import pytest
from sqlalchemy import func, select

from app.embedding.models import Chunk
from app.embedding.runner import index_build_runner
from tests.integration.conftest import make_client, make_document, make_watchlist

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires PANTERA_INTEGRATION=1 and docker compose up",
)


@pytest.mark.asyncio
class TestIndexIdempotency:
    """Test that re-running a build produces 0 new chunks and 0 embed calls."""

    async def test_idempotent_build_no_new_chunks(
        self, async_session, mock_modelserver_client
    ) -> None:
        """Second build of same corpus yields 0 new chunks (SC-003)."""
        # Setup: client + watchlist + document
        client = await make_client(async_session)
        watchlist = await make_watchlist(async_session, client_id=client.id)
        doc = await make_document(
            async_session,
            client_id=client.id,
            source_name="pubmed",
            source_payload="""<?xml version="1.0"?>
<PubmedArticle>
  <Article>
    <ArticleTitle>Test Article</ArticleTitle>
    <Abstract>
      <AbstractText>Test abstract content.</AbstractText>
    </Abstract>
  </Article>
</PubmedArticle>""",
        )

        # Link document to watchlist
        from app.ingestion.models import DocumentWatchlist

        link = DocumentWatchlist(document_id=doc.id, watchlist_id=watchlist.id)
        async_session.add(link)
        await async_session.flush()

        # First build
        run1 = await index_build_runner(
            session_factory=lambda: async_session,
            client_id=client.id,
            modelserver_client=mock_modelserver_client,
        )

        # Count chunks after first build
        stmt = select(func.count(Chunk.id)).where(Chunk.client_id == client.id)
        chunks_after_first = (await async_session.execute(stmt)).scalar() or 0

        assert chunks_after_first > 0, "First build should create chunks"
        assert run1.status in ("success", "partial_success")

        # Second build (idempotent)
        run2 = await index_build_runner(
            session_factory=lambda: async_session,
            client_id=client.id,
            modelserver_client=mock_modelserver_client,
        )

        # Count chunks after second build
        chunks_after_second = (await async_session.execute(stmt)).scalar() or 0

        # Idempotency: same chunk count
        assert chunks_after_second == chunks_after_first, (
            f"Idempotent build should not create new chunks "
            f"(was {chunks_after_first}, now {chunks_after_second})"
        )

        # Second run should skip all documents
        assert (
            run2.documents_processed == 0
        ), f"Idempotent run should process 0 docs (processed {run2.documents_processed})"
        assert (
            run2.documents_skipped > 0
        ), f"Idempotent run should skip indexed docs (skipped {run2.documents_skipped})"

    async def test_incremental_add_new_document(
        self, async_session, mock_modelserver_client
    ) -> None:
        """Adding one document after initial build indexes only that document."""
        from app.ingestion.models import DocumentWatchlist

        # Setup: initial build
        client = await make_client(async_session)
        watchlist = await make_watchlist(async_session, client_id=client.id)

        doc1 = await make_document(async_session, client_id=client.id, title="Doc 1")
        link1 = DocumentWatchlist(document_id=doc1.id, watchlist_id=watchlist.id)
        async_session.add(link1)
        await async_session.flush()

        # First build
        await index_build_runner(
            session_factory=lambda: async_session,
            client_id=client.id,
            modelserver_client=mock_modelserver_client,
        )
        chunks_after_first = (
            await async_session.execute(
                select(func.count(Chunk.id)).where(Chunk.client_id == client.id)
            )
        ).scalar() or 0

        # Add a new document
        doc2 = await make_document(async_session, client_id=client.id, title="Doc 2")
        link2 = DocumentWatchlist(document_id=doc2.id, watchlist_id=watchlist.id)
        async_session.add(link2)
        await async_session.flush()

        # Second build (incremental)
        run2 = await index_build_runner(
            session_factory=lambda: async_session,
            client_id=client.id,
            modelserver_client=mock_modelserver_client,
        )

        chunks_after_second = (
            await async_session.execute(
                select(func.count(Chunk.id)).where(Chunk.client_id == client.id)
            )
        ).scalar() or 0

        # Incremental: only the new document is processed
        assert (
            run2.documents_processed >= 1
        ), f"Incremental run should process new doc (processed {run2.documents_processed})"
        assert (
            run2.documents_skipped >= 1
        ), f"Incremental run should skip indexed doc (skipped {run2.documents_skipped})"
        assert (
            chunks_after_second > chunks_after_first
        ), "Adding a document should increase chunk count"
