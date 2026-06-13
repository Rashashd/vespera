"""Unit tests for report creation, follow-up, operator alert, and per-finding service functions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.reports.enums import FindingReportState, ReportStatus, ReportType
from app.triage.enums import FindingStatus


def _make_finding(
    id: int = 1,
    client_id: int = 10,
    status: str = "pending_expedited",
    bucket: str = "urgent",
) -> MagicMock:
    f = MagicMock()
    f.id = id
    f.client_id = client_id
    f.status = status
    f.bucket = bucket
    f.drug = "Warfarin"
    f.reaction = "bleeding"
    return f


def _make_report(id: int = 1, client_id: int = 10, status: str = "drafted") -> MagicMock:
    r = MagicMock()
    r.id = id
    r.client_id = client_id
    r.status = status
    r.report_type = "expedited"
    r.reviewer_comments = []
    return r


def _make_settings() -> MagicMock:
    s = MagicMock()
    s.expedited_sla_hours = 24
    return s


class TestCreateExpeditedReport:
    @pytest.mark.asyncio
    async def test_idempotent_returns_existing(self):
        from app.reports import service as svc

        existing_rf = MagicMock()
        existing_rf.report_id = 55
        existing_report = _make_report(id=55)

        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: existing_rf))
        session.get = AsyncMock(return_value=existing_report)

        finding = _make_finding()
        result = await svc.create_expedited_report(
            finding=finding,
            draft_outcome={"claims": [], "draft_body": "x"},
            session=session,
            settings=_make_settings(),
            dispatcher=AsyncMock(),
        )
        assert result is existing_report

    @pytest.mark.asyncio
    async def test_discarded_finding_raises_409(self):
        from app.reports import service as svc

        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))

        finding = _make_finding(status="discarded")
        with pytest.raises(HTTPException) as exc_info:
            await svc.create_expedited_report(
                finding=finding,
                draft_outcome={},
                session=session,
                settings=_make_settings(),
                dispatcher=AsyncMock(),
            )
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_creates_report_and_flips_finding_status(self):
        from app.domain.events import ReportDrafted
        from app.reports import service as svc

        finding = _make_finding(status="pending_expedited")
        dispatcher = AsyncMock()
        dispatcher.dispatch = AsyncMock()

        added = []
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
        session.add = MagicMock(side_effect=lambda obj: added.append(obj))
        session.flush = AsyncMock()

        draft_outcome = {
            "claims": [{"field": "Drug", "text": "Warfarin", "provenance": "drafted_grounded"}],
            "draft_body": "Test body",
            "corroboration_count": 2,
            "corroboration_sources": [],
        }
        result = await svc.create_expedited_report(
            finding=finding,
            draft_outcome=draft_outcome,
            session=session,
            settings=_make_settings(),
            dispatcher=dispatcher,
        )

        assert result.report_type == ReportType.EXPEDITED
        assert result.status == ReportStatus.DRAFTED
        assert finding.status == FindingStatus.PROCESSING
        dispatcher.dispatch.assert_called_once()
        event = dispatcher.dispatch.call_args.args[0]
        assert isinstance(event, ReportDrafted)


class TestCreateFollowup:
    @pytest.mark.asyncio
    async def test_idempotent_returns_existing(self):
        from app.reports import service as svc

        existing = MagicMock()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: existing))

        result = await svc.create_followup(
            finding=_make_finding(),
            report=_make_report(),
            followup_result={},
            session=session,
        )
        assert result is existing

    @pytest.mark.asyncio
    async def test_creates_new_followup(self):
        from app.reports import service as svc

        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
        added = []
        session.add = MagicMock(side_effect=lambda obj: added.append(obj))

        result = await svc.create_followup(
            finding=_make_finding(),
            report=_make_report(),
            followup_result={
                "template_ref": "emergency_author_outreach_v1",
                "cover_message": "Please review",
            },
            session=session,
        )

        assert result.template_ref == "emergency_author_outreach_v1"
        assert result.cover_message == "Please review"
        assert result.status == "generated"
        assert len(added) == 1

    @pytest.mark.asyncio
    async def test_default_template_ref_used_when_missing(self):
        from app.reports import service as svc

        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
        session.add = MagicMock()

        result = await svc.create_followup(
            finding=_make_finding(),
            report=_make_report(),
            followup_result={},
            session=session,
        )
        assert result.template_ref == "emergency_author_outreach_v1"


class TestPersistOperatorAlert:
    @pytest.mark.asyncio
    async def test_dispatches_operator_alert_event(self):
        from app.domain.events import ReportOperatorAlert
        from app.reports import service as svc

        dispatcher = AsyncMock()
        dispatcher.dispatch = AsyncMock()
        session = AsyncMock()

        await svc.persist_operator_alert(
            finding=_make_finding(id=7, client_id=10),
            reason="ungroundable_no_evidence",
            session=session,
            dispatcher=dispatcher,
        )

        dispatcher.dispatch.assert_called_once()
        event = dispatcher.dispatch.call_args.args[0]
        assert isinstance(event, ReportOperatorAlert)
        assert event.reason == "ungroundable_no_evidence"
        assert event.finding_id == 7
        assert event.client_id == 10


class TestDropFindingFromReport:
    @pytest.mark.asyncio
    async def test_drop_flips_finding_to_pending_batch(self):
        from app.reports import service as svc

        mock_rf = MagicMock()
        mock_rf.state = FindingReportState.INCLUDED
        mock_finding = _make_finding(id=5)
        mock_finding.status = "classified"

        # _maybe_auto_discard_batch fetches the Report; give it one with included findings
        # so it does NOT auto-discard (simplifies the test)
        remaining = MagicMock()
        included_mock = MagicMock()
        included_mock.scalars.return_value.all.return_value = [remaining]

        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=lambda: mock_rf),  # _load_report_finding
                included_mock,  # _maybe_auto_discard_batch count (has remaining → no discard)
            ]
        )
        # session.get called for Finding only in this path
        session.get = AsyncMock(return_value=mock_finding)

        reviewer = MagicMock()
        reviewer.id = 99
        dispatcher = AsyncMock()
        dispatcher.dispatch = AsyncMock()

        await svc.drop_finding_from_report(
            report_id=1,
            finding_id=5,
            client_id=10,
            reviewer=reviewer,
            session=session,
            dispatcher=dispatcher,
        )

        assert mock_rf.state == FindingReportState.DROPPED
        from app.triage.enums import FindingStatus

        assert mock_finding.status == FindingStatus.PENDING_BATCH

    @pytest.mark.asyncio
    async def test_report_finding_not_found_raises_404(self):
        from app.reports import service as svc

        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))

        with pytest.raises(HTTPException) as exc_info:
            await svc.drop_finding_from_report(
                report_id=1,
                finding_id=99,
                client_id=10,
                reviewer=MagicMock(),
                session=session,
                dispatcher=AsyncMock(),
            )
        assert exc_info.value.status_code == 404


class TestDiscardFindingPermanently:
    @pytest.mark.asyncio
    async def test_discard_flips_finding_to_discarded(self):
        from app.reports import service as svc

        mock_rf = MagicMock()
        mock_finding = _make_finding(id=3)

        # Has remaining findings → no auto-discard
        remaining = MagicMock()
        included_mock = MagicMock()
        included_mock.scalars.return_value.all.return_value = [remaining]

        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=lambda: mock_rf),
                included_mock,
            ]
        )
        session.get = AsyncMock(return_value=mock_finding)

        reviewer = MagicMock()
        reviewer.id = 42
        dispatcher = AsyncMock()
        dispatcher.dispatch = AsyncMock()

        await svc.discard_finding_permanently(
            report_id=1,
            finding_id=3,
            client_id=10,
            reviewer=reviewer,
            session=session,
            dispatcher=dispatcher,
        )

        assert mock_rf.state == FindingReportState.DISCARDED
        assert mock_finding.status == FindingStatus.DISCARDED


class TestMaybeAutoDiscardBatch:
    @pytest.mark.asyncio
    async def test_auto_discards_when_no_included_findings_remain(self):
        from app.domain.events import ReportDiscarded

        mock_report = _make_report(status="drafted")
        mock_report.report_type = "batch"

        included_mock = MagicMock()
        included_mock.scalars.return_value.all.return_value = []

        session = AsyncMock()
        session.execute = AsyncMock(return_value=included_mock)
        session.get = AsyncMock(return_value=mock_report)

        reviewer = MagicMock()
        reviewer.id = 1
        dispatcher = AsyncMock()
        dispatcher.dispatch = AsyncMock()

        from app.reports import _helpers

        await _helpers.maybe_auto_discard_batch(1, 10, reviewer, session, dispatcher)

        assert mock_report.status == ReportStatus.DISCARDED
        dispatcher.dispatch.assert_called_once()
        event = dispatcher.dispatch.call_args.args[0]
        assert isinstance(event, ReportDiscarded)

    @pytest.mark.asyncio
    async def test_no_auto_discard_when_included_findings_remain(self):

        remaining_rf = MagicMock()
        included_mock = MagicMock()
        included_mock.scalars.return_value.all.return_value = [remaining_rf]

        session = AsyncMock()
        session.execute = AsyncMock(return_value=included_mock)

        dispatcher = AsyncMock()
        dispatcher.dispatch = AsyncMock()

        from app.reports import _helpers

        await _helpers.maybe_auto_discard_batch(1, 10, MagicMock(), session, dispatcher)

        dispatcher.dispatch.assert_not_called()
