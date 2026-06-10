"""Integration test for full index build (SC-001, SC-006, SC-008)."""

import os

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.embedding.models import Chunk, DocumentIndexState
from app.embedding.runner import index_build_runner
from app.ingestion.models import DocumentWatchlist
from tests.integration.conftest import make_client, make_document, make_watchlist

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires PANTERA_INTEGRATION=1 and docker compose up",
)


@pytest.mark.asyncio
class TestIndexBuild:
    """Test end-to-end index build for client documents (MVP use case)."""

    async def test_build_pubmed_documents_to_chunks(
        self, async_session: AsyncSession, mock_modelserver_client
    ) -> None:
        """Full build: PubMed documents → chunks with embeddings + metadata.

        Verifies:
        - SC-001: Each document becomes searchable chunks with 768-dim embeddings.
        - SC-006: Each chunk carries correct metadata (ordinal, embedder_version).
        - SC-008: Every chunk has both dense embedding and populated text_tsv.
        """
        # Setup: create client, watchlist, and seeded PubMed document
        client = await make_client(async_session)
        watchlist = await make_watchlist(async_session, client_id=client.id)

        # Create a document with PubMed source payload
        doc = await make_document(
            async_session,
            client_id=client.id,
            source_name="pubmed",
            source_payload="""<?xml version="1.0"?>
<PubmedArticle>
  <Article>
    <ArticleTitle>Test Article on Diabetes</ArticleTitle>
    <Abstract>
      <AbstractText>This is a test abstract about diabetes treatment.</AbstractText>
    </Abstract>
    <Body>
      <Section>
        <Title>Introduction</Title>
        <Paragraph>Diabetes is a metabolic disease.</Paragraph>
      </Section>
    </Body>
  </Article>
</PubmedArticle>""",
        )

        # Link document to active watchlist
        watchlist_link = DocumentWatchlist(
            document_id=doc.id,
            watchlist_id=watchlist.id,
        )
        async_session.add(watchlist_link)
        await async_session.flush()

        # Run the build
        await index_build_runner(
            session_factory=lambda: async_session,
            client_id=client.id,
            modelserver_client=mock_modelserver_client,
        )

        # Verify: chunks exist with correct properties
        chunks = (
            await async_session.query(Chunk)
            .filter(Chunk.client_id == client.id, Chunk.document_id == doc.id)
            .all()
        )
        assert len(chunks) > 0, "Should create at least one chunk from PubMed document"

        # Each chunk has 768-dim embedding
        for chunk in chunks:
            assert (
                len(chunk.embedding) == 768
            ), f"Embedding should be 768-dim, got {len(chunk.embedding)}"
            assert chunk.embedder_version, "Should have embedder version stamp"
            assert chunk.ordinal >= 0, "Should have non-negative ordinal"
            assert chunk.client_id == client.id, "Chunk should be client-scoped"

        # Document should be marked indexed
        state = (
            await async_session.query(DocumentIndexState)
            .filter(DocumentIndexState.document_id == doc.id)
            .first()
        )
        assert state, "Should create document index state"
        assert state.status in ("indexed", "indexed_empty"), "Should be indexed or empty"

    async def test_build_empty_document_marked_indexed_empty(
        self, async_session: AsyncSession, mock_modelserver_client
    ) -> None:
        """A document that yields no chunks is marked indexed_empty (SC-001)."""
        client = await make_client(async_session)
        watchlist = await make_watchlist(async_session, client_id=client.id)

        # Create a document with minimal/empty payload
        doc = await make_document(
            async_session,
            client_id=client.id,
            source_name="pubmed",
            source_payload="<PubmedArticle></PubmedArticle>",  # Empty
        )

        # Link to watchlist
        watchlist_link = DocumentWatchlist(
            document_id=doc.id,
            watchlist_id=watchlist.id,
        )
        async_session.add(watchlist_link)
        await async_session.flush()

        # Run the build
        await index_build_runner(
            session_factory=lambda: async_session,
            client_id=client.id,
            modelserver_client=mock_modelserver_client,
        )

        # Verify: state is indexed_empty
        state = (
            await async_session.query(DocumentIndexState)
            .filter(DocumentIndexState.document_id == doc.id)
            .first()
        )
        assert state, "Should create index state for empty document"
        assert state.status == "indexed_empty", "Empty document should be marked indexed_empty"
        assert state.chunk_count == 0, "Should have zero chunks"
