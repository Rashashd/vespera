"""Integration test for hybrid-retrieval-ready index (T045-T046, SC-008, FR-015)."""

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
class TestIndexHybridReady:
    """Test that every chunk has dense embedding + lexical vector + metadata for hybrid retrieval."""

    async def test_chunks_have_dense_embedding_and_tsvector(
        self, async_session, mock_modelserver_client
    ) -> None:
        """Every chunk carries both dense embedding and populated text_tsv (SC-008)."""
        # Setup
        client = await make_client(async_session)
        watchlist = await make_watchlist(async_session, client_id=client.id)
        doc = await make_document(
            async_session,
            client_id=client.id,
            source_name="pubmed",
            source_payload="""<?xml version="1.0"?>
<PubmedArticle>
  <Article>
    <ArticleTitle>Hybrid Test Article</ArticleTitle>
    <Abstract>
      <AbstractText>Contains medical terminology for lexical search.</AbstractText>
    </Abstract>
  </Article>
</PubmedArticle>""",
        )

        from app.ingestion.models import DocumentWatchlist
        link = DocumentWatchlist(document_id=doc.id, watchlist_id=watchlist.id)
        async_session.add(link)
        await async_session.flush()

        # Index
        await index_build_runner(
            session_factory=lambda: async_session,
            client_id=client.id,
            modelserver_client=mock_modelserver_client,
        )

        # Retrieve chunks
        stmt = select(Chunk).where(Chunk.client_id == client.id)
        chunks = (await async_session.execute(stmt)).scalars().all()

        assert len(chunks) > 0, "Should have chunks"

        # Verify dense embedding
        for chunk in chunks:
            assert chunk.embedding is not None, "Chunk must have dense embedding"
            assert isinstance(chunk.embedding, list), "Embedding should be a list"
            assert len(chunk.embedding) == 768, f"Embedding must be 768-dim (got {len(chunk.embedding)})"

            # Verify it's approximately normalized (L2 norm close to 1)
            import math
            norm = math.sqrt(sum(x**2 for x in chunk.embedding))
            assert 0.9 < norm < 1.1, f"Embedding should be normalized (norm={norm})"

            # Verify lexical tsvector is not empty
            assert chunk.text_tsv is not None, "Chunk must have text_tsv"
            assert isinstance(chunk.text_tsv, str), "text_tsv should be a string"
            assert len(chunk.text_tsv) > 0, "text_tsv should be populated"

            # Verify metadata for Spec 7 filtering
            assert chunk.chunk_type is not None, "chunk_type is required"
            assert chunk.source_reliability is not None, "source_reliability is required"
            # section and date can be null but are present

    async def test_chunk_metadata_for_retrieval_filtering(
        self, async_session, mock_modelserver_client
    ) -> None:
        """Chunks have all metadata Spec 7 needs for filtering/ranking (FR-015)."""
        client = await make_client(async_session)
        watchlist = await make_watchlist(async_session, client_id=client.id)
        doc = await make_document(
            async_session,
            client_id=client.id,
            source_name="pubmed",
            source_payload="""<?xml version="1.0"?>
<PubmedArticle>
  <Article>
    <ArticleTitle>Metadata Test</ArticleTitle>
    <Abstract><AbstractText>Test.</AbstractText></Abstract>
  </Article>
</PubmedArticle>""",
        )

        from app.ingestion.models import DocumentWatchlist
        link = DocumentWatchlist(document_id=doc.id, watchlist_id=watchlist.id)
        async_session.add(link)
        await async_session.flush()

        # Index
        await index_build_runner(
            session_factory=lambda: async_session,
            client_id=client.id,
            modelserver_client=mock_modelserver_client,
        )

        # Verify metadata
        stmt = select(Chunk).where(Chunk.client_id == client.id)
        chunks = (await async_session.execute(stmt)).scalars().all()

        for chunk in chunks:
            # Required for Spec 7 filtering
            assert chunk.chunk_type is not None
            assert chunk.source_reliability is not None
            assert chunk.document_id is not None  # Link back to document

            # Optional but useful
            # section can be null for prose chunks
            # date inherited from document, can be null
            # drug always null in v1 per FR-023
            assert chunk.drug is None, "drug should be null in v1 (FR-023)"
