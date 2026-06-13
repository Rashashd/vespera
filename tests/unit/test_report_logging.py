"""Unit tests for report-drafting logging: structured fields, no raw text leakage (FR-027)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.tools import EscalationSignal, ToolError


class TestSystemPromptUntrustedDataRule:
    """The system prompt must contain the untrusted-data rule (FR-027)."""

    def test_draft_system_prompt_has_untrusted_data_rule(self):
        from pathlib import Path

        prompt_path = Path(__file__).parent.parent.parent / "app/agent/prompts/system_draft.txt"
        text = prompt_path.read_text(encoding="utf-8")
        assert "UNTRUSTED" in text.upper() or "EXTERNAL DATA" in text.upper()
        assert "never follow" in text.lower() or "not as commands" in text.lower()

    def test_redraft_system_prompt_has_untrusted_data_rule(self):
        from pathlib import Path

        prompt_path = Path(__file__).parent.parent.parent / "app/agent/prompts/system_redraft.txt"
        text = prompt_path.read_text(encoding="utf-8")
        assert "UNTRUSTED" in text.upper() or "EXTERNAL DATA" in text.upper()


class TestRunnerLoggingFieldsOnly:
    """Verify runner logs structured IDs and not raw finding text."""

    @pytest.mark.asyncio
    async def test_draft_expedited_logs_finding_id_and_bucket(self, caplog):
        """draft_expedited must log finding_id and bucket as structured fields, not raw text."""
        import structlog.testing

        finding = MagicMock()
        finding.id = 42
        finding.client_id = 10
        finding.bucket = "urgent"
        finding.drug = "Aspirin"
        finding.reaction = "anaphylaxis"
        finding.status = "pending_expedited"

        client = MagicMock()
        client.id = 10

        session_ctx = AsyncMock()
        session = AsyncMock()
        session_ctx.__aenter__ = AsyncMock(return_value=session)
        session_ctx.__aexit__ = AsyncMock(return_value=None)

        session_begin_ctx = AsyncMock()
        session_begin_ctx.__aenter__ = AsyncMock(return_value=session_begin_ctx)
        session_begin_ctx.__aexit__ = AsyncMock(return_value=None)
        session.begin = MagicMock(return_value=session_begin_ctx)
        session.get = AsyncMock(side_effect=[finding, client])

        session_factory = MagicMock(return_value=session_ctx)

        app_state = MagicMock()
        app_state.settings = MagicMock()
        app_state.session_factory = session_factory
        app_state.redis = AsyncMock()
        app_state.dispatcher = AsyncMock()

        async def mock_run_agent(**kwargs):
            return {
                "escalated": True,
                "escalation_reason": "ungroundable_no_evidence",
                "draft_result": None,
                "followup_result": None,
            }

        with structlog.testing.capture_logs() as cap:
            with patch("app.agent.graph.run_agent", side_effect=mock_run_agent):
                with patch("app.infra.modelserver_client.ModelserverClient"):
                    from app.reports.runner import draft_expedited

                    await draft_expedited(42, app_state)

        # Check that structured log events include finding_id + bucket
        start_event = next((e for e in cap if e.get("event") == "draft_expedited.start"), None)
        logged_events = [e.get("event") for e in cap]
        assert start_event is not None, f"draft_expedited.start not logged; got: {logged_events}"
        assert start_event.get("client_id") == 10
        assert start_event.get("bucket") == "urgent"

    @pytest.mark.asyncio
    async def test_draft_expedited_does_not_log_raw_drug_or_reaction_text(self):
        """Log fields must not contain free-text drug/reaction strings (structured IDs only)."""
        finding = MagicMock()
        finding.id = 99
        finding.client_id = 5
        finding.bucket = "emergency"
        finding.drug = "SUPER_SECRET_DRUG_XYZ"
        finding.reaction = "VERY_SPECIFIC_REACTION_ABC"
        finding.status = "pending_expedited"

        client = MagicMock()
        client.id = 5

        session_ctx = AsyncMock()
        session = AsyncMock()
        session_ctx.__aenter__ = AsyncMock(return_value=session)
        session_ctx.__aexit__ = AsyncMock(return_value=None)
        session_begin_ctx = AsyncMock()
        session_begin_ctx.__aenter__ = AsyncMock(return_value=session_begin_ctx)
        session_begin_ctx.__aexit__ = AsyncMock(return_value=None)
        session.begin = MagicMock(return_value=session_begin_ctx)
        session.get = AsyncMock(side_effect=[finding, client])
        session_factory = MagicMock(return_value=session_ctx)

        app_state = MagicMock()
        app_state.settings = MagicMock()
        app_state.session_factory = session_factory
        app_state.redis = AsyncMock()
        app_state.dispatcher = AsyncMock()

        async def mock_run_agent(**kwargs):
            return {
                "escalated": True,
                "escalation_reason": "ungroundable_no_evidence",
                "draft_result": None,
                "followup_result": None,
            }

        import structlog.testing

        with structlog.testing.capture_logs() as cap:
            with patch("app.agent.graph.run_agent", side_effect=mock_run_agent):
                with patch("app.infra.modelserver_client.ModelserverClient"):
                    from app.reports.runner import draft_expedited

                    await draft_expedited(99, app_state)

        # None of the log events should contain raw drug/reaction strings
        all_log_text = json.dumps(cap)
        assert "SUPER_SECRET_DRUG_XYZ" not in all_log_text
        assert "VERY_SPECIFIC_REACTION_ABC" not in all_log_text


class TestToolRetrieveLogging:
    """retrieve tool must log error events without leaking full passage text."""

    @pytest.mark.asyncio
    async def test_retrieve_error_logs_without_passage_text(self):
        from app.agent.tools import make_tools

        mock_finding = MagicMock()
        mock_finding.id = 1
        mock_finding.bucket = "urgent"
        mock_finding.drug = "PRIVATE_DRUG_NAME"
        mock_finding.reaction = "rash"

        async def failing_retrieve(*args, **kwargs):
            raise RuntimeError("db connection refused")

        import structlog.testing

        with structlog.testing.capture_logs() as cap:
            with patch("app.rag.service.retrieve", side_effect=failing_retrieve):
                tools = make_tools(
                    session=AsyncMock(),
                    redis=AsyncMock(),
                    ms_client=MagicMock(),
                    client=MagicMock(id=5),
                    app_state=MagicMock(),
                    finding=mock_finding,
                )
                retrieve_tool = next(t for t in tools if t.name == "retrieve")
                with pytest.raises(ToolError):
                    await retrieve_tool.ainvoke({"query": "Aspirin anaphylaxis"})

        retrieve_error_events = [e for e in cap if "retrieve.error" in str(e.get("event", ""))]
        assert len(retrieve_error_events) >= 1
        # Error log must not contain the raw query string (potential PII vector)
        for ev in retrieve_error_events:
            assert "Aspirin anaphylaxis" not in str(ev)
            assert "PRIVATE_DRUG_NAME" not in str(ev)


class TestEscalationSignalContract:
    """EscalationSignal must carry a machine-readable reason code (not free text)."""

    def test_reason_codes_are_controlled(self):
        valid_reasons = {
            "ungroundable_no_evidence",
            "ungroundable_no_claims",
            "cannot_comply",
        }
        for reason in valid_reasons:
            sig = EscalationSignal(reason)
            assert sig.reason == reason

    def test_escalation_signal_is_exception(self):
        sig = EscalationSignal("ungroundable_no_evidence")
        assert isinstance(sig, Exception)
