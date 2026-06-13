"""Unit tests for expedited drafting: grounding, corroboration, idempotency, score_severity."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.tools import ClaimDraft, DraftReportInput, EscalationSignal, ToolError
from app.reports.enums import ClaimProvenance, FindingReportState, ReportStatus, ReportType


class TestToolError:
    def test_retryable_true(self):
        err = ToolError("retrieval failed", retryable=True)
        assert err.retryable is True
        assert "retrieval" in str(err)

    def test_retryable_false(self):
        err = ToolError("no claims", retryable=False)
        assert err.retryable is False

    def test_escalation_signal_has_reason(self):
        sig = EscalationSignal("ungroundable_no_evidence")
        assert sig.reason == "ungroundable_no_evidence"


class TestClaimDraft:
    def test_claim_with_source_ref(self):
        c = ClaimDraft(field="Drug", text="Aspirin", source_ref="42")
        assert c.source_ref == "42"

    def test_claim_without_source_ref_is_ungroundable(self):
        c = ClaimDraft(field="Causality", text="probable")
        assert c.source_ref is None

    def test_draft_report_input_schema(self):
        inp = DraftReportInput(
            claims=[ClaimDraft(field="Drug", text="Warfarin", source_ref="7")],
            draft_body="Test body",
            corroboration_sources=[{"doc_id": 1}],
        )
        assert len(inp.claims) == 1
        assert inp.corroboration_sources[0]["doc_id"] == 1


class TestReportStatusEnum:
    def test_approved_is_terminal(self):
        assert ReportStatus.APPROVED.is_terminal is True

    def test_discarded_is_terminal(self):
        assert ReportStatus.DISCARDED.is_terminal is True

    def test_drafted_not_terminal(self):
        assert ReportStatus.DRAFTED.is_terminal is False

    def test_under_review_not_terminal(self):
        assert ReportStatus.UNDER_REVIEW.is_terminal is False

    def test_rejected_not_terminal(self):
        assert ReportStatus.REJECTED.is_terminal is False

    def test_needs_manual_revision_not_terminal(self):
        assert ReportStatus.NEEDS_MANUAL_REVISION.is_terminal is False


class TestReportTypeEnum:
    def test_expedited_value(self):
        assert ReportType.EXPEDITED == "expedited"

    def test_batch_value(self):
        assert ReportType.BATCH == "batch"


class TestClaimProvenance:
    def test_drafted_grounded(self):
        assert ClaimProvenance.DRAFTED_GROUNDED == "drafted_grounded"

    def test_reviewer_attested(self):
        assert ClaimProvenance.REVIEWER_ATTESTED == "reviewer_attested"


class TestFindingReportState:
    def test_included(self):
        assert FindingReportState.INCLUDED == "included"

    def test_dropped(self):
        assert FindingReportState.DROPPED == "dropped"

    def test_discarded(self):
        assert FindingReportState.DISCARDED == "discarded"


class TestValidateChunkRefs:
    """Test the source_ref validation helper."""

    @pytest.mark.asyncio
    async def test_valid_refs_returned(self):
        from app.agent.tools import _validate_chunk_refs

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [1, 2]
        mock_session.execute = AsyncMock(return_value=mock_result)

        valid = await _validate_chunk_refs(mock_session, client_id=99, refs=["1", "2", "999"])
        assert "1" in valid
        assert "2" in valid

    @pytest.mark.asyncio
    async def test_empty_refs_returns_empty_set(self):
        from app.agent.tools import _validate_chunk_refs

        mock_session = AsyncMock()
        valid = await _validate_chunk_refs(mock_session, client_id=99, refs=[])
        assert valid == set()

    @pytest.mark.asyncio
    async def test_non_integer_refs_skipped(self):
        from app.agent.tools import _validate_chunk_refs

        mock_session = AsyncMock()
        # If all refs are non-integers, no DB query is made
        valid = await _validate_chunk_refs(mock_session, client_id=99, refs=["abc", "xyz"])
        assert valid == set()
        mock_session.execute.assert_not_called()


class TestScoreSeverityReadOnly:
    """score_severity must read bucket, never modify it."""

    @pytest.mark.asyncio
    async def test_score_severity_returns_finding_fields(self):
        import json

        from app.agent.tools import make_tools

        mock_session = AsyncMock()
        mock_finding = MagicMock()
        mock_finding.id = 1
        mock_finding.bucket = "emergency"
        mock_finding.drug = "Aspirin"
        mock_finding.reaction = "anaphylaxis"

        tools = make_tools(
            session=mock_session,
            redis=AsyncMock(),
            ms_client=MagicMock(),
            client=MagicMock(id=5),
            app_state=MagicMock(),
            finding=mock_finding,
        )
        score_tool = next(t for t in tools if t.name == "score_severity")
        result_json = await score_tool.ainvoke({})
        result = json.loads(result_json)

        assert result["bucket"] == "emergency"
        assert result["drug"] == "Aspirin"
        assert result["reaction"] == "anaphylaxis"
        # Must not have mutated the finding's bucket
        assert mock_finding.bucket == "emergency"
