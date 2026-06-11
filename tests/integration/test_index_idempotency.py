"""Integration test for idempotent index builds (T031-T032, SC-003)."""

import os

import pytest
from sqlalchemy import func, select

from app.embedding.models import Chunk
from app.embedding.runner import index_build_runner

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires PANTERA_INTEGRATION=1 and docker compose up",
)

_PUBMED_XML = """<?xml version="1.0"?>
<PubmedArticle>
  <Article>
    <ArticleTitle>Test Article</ArticleTitle>
    <Abstract>
      <AbstractText>Test abstract content.</AbstractText>
    </Abstract>
  </Article>
</PubmedArticle>"""


@pytest.mark.asyncio
class TestIndexIdempotency:
    """Test that re-running a build produces 0 new chunks."""

    async def _count_chunks(self, session_factory, client_id: int) -> int:
        async with session_factory() as s:
            return (
                await s.execute(select(func.count(Chunk.id)).where(Chunk.client_id == client_id))
            ).scalar() or 0

    async def test_idempotent_build_no_new_chunks(
        self, auth_app, make_client, make_watchlist, make_document, mock_modelserver_client
    ) -> None:
        """Second build of same corpus yields 0 new chunks (SC-003)."""
        session_factory = auth_app.state.session_factory
        client = await make_client()
        watchlist = await make_watchlist(client_id=client.id)
        await make_document(
            client_id=client.id,
            source_name="pubmed",
            source_payload=_PUBMED_XML,
            watchlist_id=watchlist.id,
        )

        run1 = await index_build_runner(
            session_factory=session_factory,
            client_id=client.id,
            modelserver_client=mock_modelserver_client,
        )
        chunks_after_first = await self._count_chunks(session_factory, client.id)
        assert chunks_after_first > 0, "First build should create chunks"
        assert run1.status in ("success", "partial_success")

        run2 = await index_build_runner(
            session_factory=session_factory,
            client_id=client.id,
            modelserver_client=mock_modelserver_client,
        )
        chunks_after_second = await self._count_chunks(session_factory, client.id)

        assert chunks_after_second == chunks_after_first, (
            f"Idempotent build should not create new chunks "
            f"(was {chunks_after_first}, now {chunks_after_second})"
        )
        # Idempotency is enforced at the query level: already-indexed documents are excluded
        # from the work set, so the second run processes nothing and creates no chunks.
        assert (
            run2.documents_processed == 0
        ), f"Idempotent run should process 0 docs (processed {run2.documents_processed})"
        assert run2.status == "success", f"Empty idempotent run should succeed (got {run2.status})"

    async def test_incremental_add_new_document(
        self, auth_app, make_client, make_watchlist, make_document, mock_modelserver_client
    ) -> None:
        """Adding one document after initial build indexes only that document."""
        session_factory = auth_app.state.session_factory
        client = await make_client()
        watchlist = await make_watchlist(client_id=client.id)

        await make_document(
            client_id=client.id,
            source_name="pubmed",
            source_payload=_PUBMED_XML,
            title="Doc 1",
            watchlist_id=watchlist.id,
        )

        await index_build_runner(
            session_factory=session_factory,
            client_id=client.id,
            modelserver_client=mock_modelserver_client,
        )
        chunks_after_first = await self._count_chunks(session_factory, client.id)

        await make_document(
            client_id=client.id,
            source_name="pubmed",
            source_payload=_PUBMED_XML,
            title="Doc 2",
            watchlist_id=watchlist.id,
        )

        run2 = await index_build_runner(
            session_factory=session_factory,
            client_id=client.id,
            modelserver_client=mock_modelserver_client,
        )
        chunks_after_second = await self._count_chunks(session_factory, client.id)

        # Only the newly added document is in the work set; the already-indexed one is excluded.
        assert (
            run2.documents_processed == 1
        ), f"Incremental run should process only the new doc (processed {run2.documents_processed})"
        assert (
            chunks_after_second > chunks_after_first
        ), "Adding a document should increase chunk count"
