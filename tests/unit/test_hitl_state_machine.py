"""Unit tests for HITL state machine: transitions, redraft cap, role refusal, edit provenance."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.reports.enums import ClaimProvenance, ReportStatus


def _make_report(
    status: str = "drafted",
    revision_count: int = 0,
    report_type: str = "expedited",
    reviewer_comments: list | None = None,
) -> MagicMock:
    r = MagicMock()
    r.id = 1
    r.client_id = 10
    r.status = status
    r.revision_count = revision_count
    r.report_type = report_type
    r.reviewer_comments = reviewer_comments or []
    r.structured_fields = [{"field": "Drug", "text": "Warfarin", "provenance": "drafted_grounded"}]
    r.draft_body = "Prior draft body."
    r.updated_at = None
    return r


def _make_reviewer(reviewer_id: int = 99) -> MagicMock:
    u = MagicMock()
    u.id = reviewer_id
    return u


def _settings() -> MagicMock:
    """Settings stub with redaction disabled — keeps these state-machine unit tests off Presidio."""
    s = MagicMock()
    s.redaction_enabled = False
    return s


class TestApproveTransitions:
    @pytest.mark.asyncio
    async def test_approve_from_drafted(self):
        from app.reports import service as svc

        report = _make_report(status="drafted")
        session = AsyncMock()
        session.get = AsyncMock(return_value=report)
        dispatcher = AsyncMock()
        dispatcher.dispatch = AsyncMock()

        # Patch _mark_expedited_finding_reported to be a no-op
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("app.reports.review.mark_expedited_finding_reported", AsyncMock())
            result = await svc.approve_report(
                report_id=1,
                client_id=10,
                reviewer=_make_reviewer(),
                session=session,
                dispatcher=dispatcher,
            )

        assert result.status == ReportStatus.APPROVED
        assert any(c.get("action") == "approve" for c in result.reviewer_comments)

    @pytest.mark.asyncio
    async def test_approve_from_under_review(self):
        from app.reports import service as svc

        report = _make_report(status="under_review")
        session = AsyncMock()
        session.get = AsyncMock(return_value=report)
        dispatcher = AsyncMock()
        dispatcher.dispatch = AsyncMock()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("app.reports.review.mark_expedited_finding_reported", AsyncMock())
            result = await svc.approve_report(
                report_id=1,
                client_id=10,
                reviewer=_make_reviewer(),
                session=session,
                dispatcher=dispatcher,
            )

        assert result.status == ReportStatus.APPROVED

    @pytest.mark.asyncio
    async def test_approve_already_approved_raises_409(self):
        from app.reports import service as svc

        report = _make_report(status="approved")
        session = AsyncMock()
        session.get = AsyncMock(return_value=report)

        with pytest.raises(HTTPException) as exc_info:
            await svc.approve_report(
                report_id=1,
                client_id=10,
                reviewer=_make_reviewer(),
                session=session,
                dispatcher=AsyncMock(),
            )
        assert exc_info.value.status_code == 409


class TestRejectAndRedraftCap:
    @pytest.mark.asyncio
    async def test_reject_increments_revision_count(self):
        from app.reports import service as svc

        report = _make_report(status="drafted", revision_count=0)
        session = AsyncMock()
        session.get = AsyncMock(return_value=report)
        dispatcher = AsyncMock()
        dispatcher.dispatch = AsyncMock()

        result = await svc.reject_report(
            report_id=1,
            client_id=10,
            reviewer=_make_reviewer(),
            comment="Needs more evidence",
            redraft_cap=3,
            session=session,
            dispatcher=dispatcher,
            settings=_settings(),
        )

        assert result.revision_count == 1
        assert result.status == ReportStatus.DRAFTED

    @pytest.mark.asyncio
    async def test_third_rejection_still_redrafts(self):
        from app.reports import service as svc

        # revision_count=2 + this rejection = 3 == cap(3): still a redraft round (FR-016/SC-005)
        report = _make_report(status="drafted", revision_count=2)
        session = AsyncMock()
        session.get = AsyncMock(return_value=report)
        dispatcher = AsyncMock()
        dispatcher.dispatch = AsyncMock()

        result = await svc.reject_report(
            report_id=1,
            client_id=10,
            reviewer=_make_reviewer(),
            comment="Third round, redraft again",
            redraft_cap=3,
            session=session,
            dispatcher=dispatcher,
            settings=_settings(),
        )

        assert result.status == ReportStatus.DRAFTED
        assert result.revision_count == 3

    @pytest.mark.asyncio
    async def test_fourth_rejection_triggers_needs_manual_revision(self):
        from app.reports import service as svc

        # revision_count=3 + this rejection = 4 > cap(3): escalate on the 4th rejection
        report = _make_report(status="drafted", revision_count=3)
        session = AsyncMock()
        session.get = AsyncMock(return_value=report)
        dispatcher = AsyncMock()
        dispatcher.dispatch = AsyncMock()

        result = await svc.reject_report(
            report_id=1,
            client_id=10,
            reviewer=_make_reviewer(),
            comment="Still not good after 3 redrafts",
            redraft_cap=3,
            session=session,
            dispatcher=dispatcher,
            settings=_settings(),
        )

        assert result.status == ReportStatus.NEEDS_MANUAL_REVISION
        assert result.revision_count == 4

    @pytest.mark.asyncio
    async def test_rejection_comment_appended_to_history(self):
        from app.reports import service as svc

        report = _make_report(status="drafted", revision_count=0, reviewer_comments=[])
        session = AsyncMock()
        session.get = AsyncMock(return_value=report)
        dispatcher = AsyncMock()
        dispatcher.dispatch = AsyncMock()

        result = await svc.reject_report(
            report_id=1,
            client_id=10,
            reviewer=_make_reviewer(reviewer_id=42),
            comment="Improve grounding",
            redraft_cap=3,
            session=session,
            dispatcher=dispatcher,
            settings=_settings(),
        )

        assert len(result.reviewer_comments) == 1
        comment = result.reviewer_comments[0]
        assert comment["action"] == "reject"
        assert comment["comment"] == "Improve grounding"
        assert comment["reviewer_id"] == 42


class TestEditApproveProvenance:
    @pytest.mark.asyncio
    async def test_edit_approve_tags_claims_reviewer_attested(self):
        from app.reports import service as svc

        report = _make_report(status="drafted")
        report.structured_fields = [
            {"field": "Drug", "text": "Warfarin", "provenance": "drafted_grounded"},
        ]
        session = AsyncMock()
        session.get = AsyncMock(return_value=report)
        dispatcher = AsyncMock()
        dispatcher.dispatch = AsyncMock()

        new_fields = [{"field": "Drug", "text": "Warfarin (corrected)", "provenance": "anything"}]

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("app.reports.review.mark_expedited_finding_reported", AsyncMock())
            result = await svc.edit_approve_report(
                report_id=1,
                client_id=10,
                reviewer=_make_reviewer(),
                draft_body="Updated body",
                structured_fields=new_fields,
                comment="Fixed drug name",
                session=session,
                dispatcher=dispatcher,
                settings=_settings(),
            )

        assert result.status == ReportStatus.APPROVED
        # All claims must be tagged reviewer_attested
        for claim in result.structured_fields:
            assert claim["provenance"] == ClaimProvenance.REVIEWER_ATTESTED


class TestDiscardTransition:
    @pytest.mark.asyncio
    async def test_discard_drafted_report(self):
        from app.reports import service as svc

        report = _make_report(status="drafted")
        session = AsyncMock()
        session.get = AsyncMock(return_value=report)
        mock_rf = MagicMock()
        mock_rf.report_type = "expedited"
        mock_rf.finding_id = 5
        mock_finding = MagicMock()
        mock_finding.status = "processing"
        scalars_mock = MagicMock(all=lambda: [mock_rf])
        session.execute = AsyncMock(return_value=MagicMock(scalars=lambda: scalars_mock))
        session.get = AsyncMock(side_effect=[report, mock_finding])
        dispatcher = AsyncMock()
        dispatcher.dispatch = AsyncMock()

        result = await svc.discard_report(
            report_id=1,
            client_id=10,
            reviewer=_make_reviewer(),
            session=session,
            dispatcher=dispatcher,
        )

        assert result.status == ReportStatus.DISCARDED

    @pytest.mark.asyncio
    async def test_discard_already_terminal_raises_409(self):
        from app.reports import service as svc

        report = _make_report(status="approved")
        session = AsyncMock()
        session.get = AsyncMock(return_value=report)

        with pytest.raises(HTTPException) as exc_info:
            await svc.discard_report(
                report_id=1,
                client_id=10,
                reviewer=_make_reviewer(),
                session=session,
                dispatcher=AsyncMock(),
            )
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_report_not_found_raises_404(self):
        from app.reports import service as svc

        session = AsyncMock()
        session.get = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await svc.approve_report(
                report_id=999,
                client_id=10,
                reviewer=_make_reviewer(),
                session=session,
                dispatcher=AsyncMock(),
            )
        assert exc_info.value.status_code == 404


class TestReviewTransitionGuardsAndBranches:
    """Cover the invalid-status guards and finding-reset branches the happy-path tests skip."""

    @pytest.mark.asyncio
    async def test_edit_approve_invalid_status_raises_409(self):
        from app.reports import service as svc

        session = AsyncMock()
        session.get = AsyncMock(return_value=_make_report(status="approved"))
        with pytest.raises(HTTPException) as exc:
            await svc.edit_approve_report(
                report_id=1,
                client_id=10,
                reviewer=_make_reviewer(),
                draft_body="x",
                structured_fields=[],
                comment="c",
                session=session,
                dispatcher=AsyncMock(),
                settings=_settings(),
            )
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_reject_invalid_status_raises_409(self):
        from app.reports import service as svc

        session = AsyncMock()
        session.get = AsyncMock(return_value=_make_report(status="approved"))
        with pytest.raises(HTTPException) as exc:
            await svc.reject_report(
                report_id=1,
                client_id=10,
                reviewer=_make_reviewer(),
                comment="c",
                redraft_cap=3,
                session=session,
                dispatcher=AsyncMock(),
                settings=_settings(),
            )
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_edit_approve_keeps_unchanged_grounded_claim(self):
        """A submitted claim identical to a drafted_grounded original keeps its provenance."""
        from app.reports import service as svc

        report = _make_report(status="drafted")
        report.structured_fields = [
            {
                "field": "Drug",
                "text": "Warfarin",
                "provenance": "drafted_grounded",
                "source_ref": "S1",
            }
        ]
        session = AsyncMock()
        session.get = AsyncMock(return_value=report)
        submitted = [{"field": "Drug", "text": "Warfarin", "provenance": "ignored"}]

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("app.reports.review.mark_expedited_finding_reported", AsyncMock())
            result = await svc.edit_approve_report(
                report_id=1,
                client_id=10,
                reviewer=_make_reviewer(),
                draft_body="body",
                structured_fields=submitted,
                comment="c",
                session=session,
                dispatcher=AsyncMock(),
                settings=_settings(),
            )

        kept = result.structured_fields[0]
        assert kept["provenance"] == "drafted_grounded"  # original kept, not reviewer_attested
        assert kept["source_ref"] == "S1"

    @pytest.mark.asyncio
    async def test_discard_skips_non_expedited_and_non_processing_findings(self):
        """Batch report_findings and expedited findings not in 'processing' are left untouched."""
        from app.reports import service as svc

        report = _make_report(status="drafted")
        rf_batch = MagicMock(report_type="batch", finding_id=1)
        rf_exp = MagicMock(report_type="expedited", finding_id=2)
        scalars = MagicMock(all=lambda: [rf_batch, rf_exp])
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalars=lambda: scalars))
        # load_report_for_client, then the expedited finding (status != processing → skipped).
        session.get = AsyncMock(side_effect=[report, MagicMock(status="pending_expedited")])

        result = await svc.discard_report(
            report_id=1,
            client_id=10,
            reviewer=_make_reviewer(),
            session=session,
            dispatcher=AsyncMock(),
        )
        assert result.status == ReportStatus.DISCARDED

    @pytest.mark.asyncio
    async def test_drop_finding_when_finding_row_missing_still_dispatches(self):
        from app.reports.review import drop_finding_from_report

        session = AsyncMock()
        session.get = AsyncMock(return_value=None)  # finding row already gone
        dispatcher = AsyncMock()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "app.reports.review.load_report_finding", AsyncMock(return_value=MagicMock())
            )
            mp.setattr("app.reports.review.maybe_auto_discard_batch", AsyncMock())
            await drop_finding_from_report(
                report_id=1,
                finding_id=5,
                client_id=10,
                reviewer=_make_reviewer(),
                session=session,
                dispatcher=dispatcher,
            )
        dispatcher.dispatch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_discard_finding_permanently_when_finding_row_missing(self):
        from app.reports.review import discard_finding_permanently

        session = AsyncMock()
        session.get = AsyncMock(return_value=None)
        dispatcher = AsyncMock()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "app.reports.review.load_report_finding", AsyncMock(return_value=MagicMock())
            )
            mp.setattr("app.reports.review.maybe_auto_discard_batch", AsyncMock())
            await discard_finding_permanently(
                report_id=1,
                finding_id=5,
                client_id=10,
                reviewer=_make_reviewer(),
                session=session,
                dispatcher=dispatcher,
            )
        dispatcher.dispatch.assert_awaited_once()
