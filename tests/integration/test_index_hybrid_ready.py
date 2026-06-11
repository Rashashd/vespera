"""Integration test for hybrid-retrieval-ready index (T045-T046, SC-008, FR-015)."""

import math
import os

import pytest
from sqlalchemy import select

from app.embedding.models import Chunk
from app.embedding.runner import index_build_runner

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires PANTERA_INTEGRATION=1 and docker compose up",
)


@pytest.mark.asyncio
class TestIndexHybridReady:
    """Every chunk has dense embedding + lexical vector + metadata for hybrid retrieval."""

    async def test_chunks_have_dense_embedding_and_tsvector(
        self, auth_app, make_client, make_watchlist, make_document, mock_modelserver_client
    ) -> None:
        """Every chunk carries both dense embedding and populated text_tsv (SC-008)."""
        session_factory = auth_app.state.session_factory
        client = await make_client()
        watchlist = await make_watchlist(client_id=client.id)
        await make_document(
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
            watchlist_id=watchlist.id,
        )

        await index_build_runner(
            session_factory=session_factory,
            client_id=client.id,
            modelserver_client=mock_modelserver_client,
        )

        async with session_factory() as s:
            chunks = (
                (await s.execute(select(Chunk).where(Chunk.client_id == client.id))).scalars().all()
            )

        assert len(chunks) > 0, "Should have chunks"
        for chunk in chunks:
            assert chunk.embedding is not None, "Chunk must have dense embedding"
            # pgvector deserializes to a numpy array; treat it as a 768-length float sequence.
            embedding = list(chunk.embedding)
            assert len(embedding) == 768, f"Embedding must be 768-dim (got {len(embedding)})"

            norm = math.sqrt(sum(float(x) ** 2 for x in embedding))
            assert 0.9 < norm < 1.1, f"Embedding should be normalized (norm={norm})"

            assert chunk.text_tsv is not None, "Chunk must have text_tsv"
            assert isinstance(chunk.text_tsv, str), "text_tsv should be a string"
            assert len(chunk.text_tsv) > 0, "text_tsv should be populated"

            assert chunk.chunk_type is not None, "chunk_type is required"
            assert chunk.source_reliability is not None, "source_reliability is required"

    async def test_chunk_metadata_for_retrieval_filtering(
        self, auth_app, make_client, make_watchlist, make_document, mock_modelserver_client
    ) -> None:
        """Chunks have all metadata Spec 7 needs for filtering/ranking (FR-015)."""
        session_factory = auth_app.state.session_factory
        client = await make_client()
        watchlist = await make_watchlist(client_id=client.id)
        await make_document(
            client_id=client.id,
            source_name="pubmed",
            source_payload="""<?xml version="1.0"?>
<PubmedArticle>
  <Article>
    <ArticleTitle>Metadata Test</ArticleTitle>
    <Abstract><AbstractText>Test.</AbstractText></Abstract>
  </Article>
</PubmedArticle>""",
            watchlist_id=watchlist.id,
        )

        await index_build_runner(
            session_factory=session_factory,
            client_id=client.id,
            modelserver_client=mock_modelserver_client,
        )

        async with session_factory() as s:
            chunks = (
                (await s.execute(select(Chunk).where(Chunk.client_id == client.id))).scalars().all()
            )

        assert len(chunks) > 0, "Should have chunks"
        for chunk in chunks:
            assert chunk.chunk_type is not None
            assert chunk.source_reliability is not None
            assert chunk.document_id is not None
            assert chunk.drug is None, "drug should be null in v1 (FR-023)"
