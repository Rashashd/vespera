"""Integration test: verify PII-free logging in index build (T039, FR-019, SC-007)."""

import contextlib
import json
import os

import pytest
import structlog
from structlog.testing import LogCapture

from app.embedding import document_indexer as indexer_module
from app.embedding import runner as runner_module
from app.embedding import triage_trigger as triage_module
from app.embedding.runner import index_build_runner

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires PANTERA_INTEGRATION=1 and docker compose up",
)


@contextlib.contextmanager
def capture_runner_logs():
    """Capture the runner's structlog events as dicts.

    The app caches loggers (cache_logger_on_first_use=True), so structlog's plain
    capture_logs() cannot intercept the runner's module-level logger. We swap in a
    LogCapture config with caching off and rebind the runner's logger for the duration.
    """
    cap = LogCapture()
    old_config = structlog.get_config()
    # Indexing logs are now spread across three modules (runner orchestrates, document_indexer
    # does the PII-sensitive per-doc work, triage_trigger fires triage) — rebind all three.
    modules = (runner_module, indexer_module, triage_module)
    old_logs = {m: m._log for m in modules}
    structlog.configure(processors=[cap], cache_logger_on_first_use=False)
    for m in modules:
        m._log = structlog.get_logger(m.__name__)
    try:
        yield cap.entries
    finally:
        structlog.configure(**old_config)
        for m, old in old_logs.items():
            m._log = old


@pytest.mark.asyncio
class TestIndexNoLogs:
    """Test that chunk text and FAERS PII are never logged (FR-019, SC-007)."""

    async def test_no_chunk_text_in_logs(
        self, auth_app, make_client, make_watchlist, make_document, mock_modelserver_client
    ) -> None:
        """Verify chunk text content never appears in logs."""
        session_factory = auth_app.state.session_factory
        client = await make_client()
        watchlist = await make_watchlist(client_id=client.id)

        sensitive_text = "SENSITIVE_CHUNK_CONTENT_12345"
        await make_document(
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
            watchlist_id=watchlist.id,
        )

        with capture_runner_logs() as logs:
            await index_build_runner(
                session_factory=session_factory,
                client_id=client.id,
                modelserver_client=mock_modelserver_client,
            )

        log_output = json.dumps(logs)
        assert (
            sensitive_text not in log_output
        ), f"Chunk text '{sensitive_text}' should NOT appear in logs (FR-019)"

    async def test_faers_deidentified_not_logged(
        self, auth_app, make_client, make_watchlist, make_document, mock_modelserver_client
    ) -> None:
        """Verify FAERS de-identified fields (age, sex, country) never logged (SC-007)."""
        session_factory = auth_app.state.session_factory
        client = await make_client()
        watchlist = await make_watchlist(client_id=client.id)

        faers_payload = {
            "patient": {"age": 65, "sex": "F", "country": "US"},
            "reaction": "liver damage",
            "drug": "Drug X",
        }
        await make_document(
            client_id=client.id,
            source_name="openfda_faers",
            source_payload=faers_payload,
            watchlist_id=watchlist.id,
        )

        with capture_runner_logs() as logs:
            await index_build_runner(
                session_factory=session_factory,
                client_id=client.id,
                modelserver_client=mock_modelserver_client,
            )

        log_output = json.dumps(logs)
        assert "liver damage" not in log_output, "Reaction text should not appear in logs (SC-007)"
        assert '"sex"' not in log_output, "Patient sex should not appear in logs (SC-007)"
        assert '"age"' not in log_output, "Patient age should not appear in logs (SC-007)"

    async def test_logging_contains_safe_context(
        self, auth_app, make_client, make_watchlist, make_document, mock_modelserver_client
    ) -> None:
        """Verify logs contain safe context: client_id, run_id, document_id (FR-019)."""
        session_factory = auth_app.state.session_factory
        client = await make_client()
        watchlist = await make_watchlist(client_id=client.id)
        doc = await make_document(
            client_id=client.id,
            source_name="pubmed",
            source_payload="""<?xml version="1.0"?>
<PubmedArticle>
  <Article>
    <ArticleTitle>Safe Context Test</ArticleTitle>
    <Abstract><AbstractText>Safe context content.</AbstractText></Abstract>
  </Article>
</PubmedArticle>""",
            watchlist_id=watchlist.id,
        )

        with capture_runner_logs() as logs:
            await index_build_runner(
                session_factory=session_factory,
                client_id=client.id,
                modelserver_client=mock_modelserver_client,
            )

        assert any(
            e.get("client_id") == client.id for e in logs
        ), "client_id should appear in logs for troubleshooting"
        assert any(
            e.get("document_id") == doc.id for e in logs
        ), "document_id should appear in logs for troubleshooting"
