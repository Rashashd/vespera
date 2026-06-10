"""Integration test: verify PII-free logging in index build (T039, FR-019, SC-007)."""

import json
import os

import pytest

from app.embedding.runner import index_build_runner
from tests.integration.conftest import make_client, make_document, make_watchlist

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires PANTERA_INTEGRATION=1 and docker compose up",
)


@pytest.mark.asyncio
class TestIndexNoLogs:
    """Test that chunk text and FAERS PII are never logged (FR-019, SC-007)."""

    async def test_no_chunk_text_in_logs(
        self, async_session, mock_modelserver_client, caplog
    ) -> None:
        """Verify chunk text content never appears in logs."""
        # Setup
        client = await make_client(async_session)
        watchlist = await make_watchlist(async_session, client_id=client.id)

        sensitive_text = "SENSITIVE_CHUNK_CONTENT_12345"
        doc = await make_document(
            async_session,
            client_id=client.id,
            source_name="pubmed",
            source_payload=f"""<?xml version="1.0"?>
<PubmedArticle>
  <Article>
    <ArticleTitle>Test Article</ArticleTitle>
    <Abstract>
      <AbstractText>{sensitive_text}</AbstractText>
    </Abstract>
  </Article>
</PubmedArticle>""",
        )

        from app.ingestion.models import DocumentWatchlist

        link = DocumentWatchlist(document_id=doc.id, watchlist_id=watchlist.id)
        async_session.add(link)
        await async_session.flush()

        # Index (captures logs)
        with caplog.at_level("INFO"):
            await index_build_runner(
                session_factory=lambda: async_session,
                client_id=client.id,
                modelserver_client=mock_modelserver_client,
            )

        # Verify sensitive text NOT in logs
        log_output = caplog.text
        assert (
            sensitive_text not in log_output
        ), f"Chunk text '{sensitive_text}' should NOT appear in logs (FR-019)"

    async def test_faers_deidentified_not_logged(
        self, async_session, mock_modelserver_client, caplog
    ) -> None:
        """Verify FAERS de-identified fields (age, sex, country) never logged (SC-007)."""
        client = await make_client(async_session)
        watchlist = await make_watchlist(async_session, client_id=client.id)

        # FAERS payload with PII
        faers_payload = {
            "patient": {
                "age": 65,  # PII
                "sex": "F",  # PII
                "country": "US",  # PII
            },
            "reaction": "liver damage",
            "drug": "Drug X",
        }

        doc = await make_document(
            async_session,
            client_id=client.id,
            source_name="openfda_faers",
            source_payload=json.dumps(faers_payload),
        )

        from app.ingestion.models import DocumentWatchlist

        link = DocumentWatchlist(document_id=doc.id, watchlist_id=watchlist.id)
        async_session.add(link)
        await async_session.flush()

        # Index
        with caplog.at_level("INFO"):
            await index_build_runner(
                session_factory=lambda: async_session,
                client_id=client.id,
                modelserver_client=mock_modelserver_client,
            )

        # Verify PII NOT in logs
        log_output = caplog.text
        assert (
            "age" not in log_output or "65" not in log_output
        ), "Patient age should not appear in logs (SC-007)"
        assert (
            '"F"' not in log_output and "sex" not in log_output
        ), "Patient sex should not appear in logs (SC-007)"
        assert (
            "US" not in log_output or "country" not in log_output
        ), "Patient country should not appear in logs (SC-007)"

    async def test_logging_contains_safe_context(
        self, async_session, mock_modelserver_client, caplog
    ) -> None:
        """Verify logs contain safe context: client_id, run_id, document_id (FR-019)."""
        client = await make_client(async_session)
        watchlist = await make_watchlist(async_session, client_id=client.id)
        doc = await make_document(async_session, client_id=client.id)

        from app.ingestion.models import DocumentWatchlist

        link = DocumentWatchlist(document_id=doc.id, watchlist_id=watchlist.id)
        async_session.add(link)
        await async_session.flush()

        # Index
        with caplog.at_level("INFO"):
            await index_build_runner(
                session_factory=lambda: async_session,
                client_id=client.id,
                modelserver_client=mock_modelserver_client,
            )

        # Verify SAFE context appears
        log_output = caplog.text
        assert str(client.id) in log_output, "client_id should appear in logs for troubleshooting"
        assert str(doc.id) in log_output, "document_id should appear in logs for troubleshooting"
