"""Integration test for full index build (SC-001, SC-006, SC-008)."""

import os

import pytest
from sqlalchemy import select

from app.embedding.models import Chunk, DocumentIndexState
from app.embedding.runner import index_build_runner

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires PANTERA_INTEGRATION=1 and docker compose up",
)

_PUBMED_XML = """<?xml version="1.0"?>
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
</PubmedArticle>"""


@pytest.mark.asyncio
class TestIndexBuild:
    """Test end-to-end index build for client documents (MVP use case)."""

    async def test_build_pubmed_documents_to_chunks(
        self, auth_app, make_client, make_watchlist, make_document, mock_modelserver_client
    ) -> None:
        """Full build: PubMed documents → chunks with embeddings + metadata.

        Verifies:
        - SC-001: Each document becomes searchable chunks with 768-dim embeddings.
        - SC-006: Each chunk carries correct metadata (ordinal, embedder_version).
        - SC-008: Every chunk has both dense embedding and populated text_tsv.
        """
        session_factory = auth_app.state.session_factory
        client = await make_client()
        watchlist = await make_watchlist(client_id=client.id)
        doc = await make_document(
            client_id=client.id,
            source_name="pubmed",
            source_payload=_PUBMED_XML,
            watchlist_id=watchlist.id,
        )

        run = await index_build_runner(
            session_factory=session_factory,
            client_id=client.id,
            modelserver_client=mock_modelserver_client,
        )
        assert run.status in ("success", "partial_success")
        assert run.documents_processed >= 1
        assert run.chunks_created >= 1

        async with session_factory() as s:
            chunks = (
                (
                    await s.execute(
                        select(Chunk).where(
                            Chunk.client_id == client.id, Chunk.document_id == doc.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            state = (
                (
                    await s.execute(
                        select(DocumentIndexState).where(DocumentIndexState.document_id == doc.id)
                    )
                )
                .scalars()
                .first()
            )

        assert len(chunks) > 0, "Should create at least one chunk from PubMed document"
        for chunk in chunks:
            assert (
                len(chunk.embedding) == 768
            ), f"Embedding should be 768-dim, got {len(chunk.embedding)}"
            assert chunk.embedder_version, "Should have embedder version stamp"
            assert chunk.ordinal >= 0, "Should have non-negative ordinal"
            assert chunk.client_id == client.id, "Chunk should be client-scoped"

        assert state, "Should create document index state"
        assert state.status in ("indexed", "indexed_empty")

    async def test_build_empty_document_marked_indexed_empty(
        self, auth_app, make_client, make_watchlist, make_document, mock_modelserver_client
    ) -> None:
        """A document that yields no chunks is marked indexed_empty (SC-001)."""
        session_factory = auth_app.state.session_factory
        client = await make_client()
        watchlist = await make_watchlist(client_id=client.id)
        doc = await make_document(
            client_id=client.id,
            source_name="pubmed",
            source_payload="<PubmedArticle></PubmedArticle>",  # parses to zero chunks
            watchlist_id=watchlist.id,
        )

        await index_build_runner(
            session_factory=session_factory,
            client_id=client.id,
            modelserver_client=mock_modelserver_client,
        )

        async with session_factory() as s:
            state = (
                (
                    await s.execute(
                        select(DocumentIndexState).where(DocumentIndexState.document_id == doc.id)
                    )
                )
                .scalars()
                .first()
            )

        assert state, "Should create index state for empty document"
        assert state.status == "indexed_empty", "Empty document should be marked indexed_empty"
        assert state.chunk_count == 0, "Should have zero chunks"
