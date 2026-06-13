"""Unit tests for report runner: draft_expedited and redraft_report paths."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_app_state(session_factory=None):
    app_state = MagicMock()
    app_state.settings = MagicMock()
    app_state.settings.expedited_sla_hours = 24
    app_state.redis = AsyncMock()
    app_state.dispatcher = AsyncMock()
    app_state.dispatcher.dispatch = AsyncMock()
    app_state.session_factory = session_factory or _make_session_factory()
    return app_state


def _make_session_factory(finding=None, client=None, report=None, report_finding=None):
    """Build a session factory that returns the given mocks in sequence."""
    session_ctx = AsyncMock()
    session = AsyncMock()
    session_ctx.__aenter__ = AsyncMock(return_value=session)
    session_ctx.__aexit__ = AsyncMock(return_value=None)

    session_begin_ctx = AsyncMock()
    session_begin_ctx.__aenter__ = AsyncMock(return_value=session_begin_ctx)
    session_begin_ctx.__aexit__ = AsyncMock(return_value=None)
    session.begin = MagicMock(return_value=session_begin_ctx)

    if finding is not None or client is not None:
        side_effects = []
        if finding is not None:
            side_effects.append(finding)
        if client is not None:
            side_effects.append(client)
        if report is not None:
            side_effects.append(report)
        session.get = AsyncMock(side_effect=side_effects)
    else:
        session.get = AsyncMock(return_value=None)

    if report_finding is not None:
        session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=lambda: report_finding)
        )

    return MagicMock(return_value=session_ctx)


class TestDraftExpeditedNotFound:
    @pytest.mark.asyncio
    async def test_finding_not_found_logs_warning(self):
        import structlog.testing

        app_state = _make_app_state(_make_session_factory(finding=None, client=None))
        app_state.session_factory.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=None
        )

        with structlog.testing.capture_logs() as cap:
            from app.reports.runner import draft_expedited

            await draft_expedited(999, app_state)

        warning_events = [e for e in cap if "not_found" in str(e.get("event", ""))]
        assert len(warning_events) >= 1

    @pytest.mark.asyncio
    async def test_client_not_found_logs_warning(self):
        import structlog.testing

        finding = MagicMock()
        finding.id = 1
        finding.client_id = 10
        finding.bucket = "urgent"

        session_ctx = AsyncMock()
        session = AsyncMock()
        session_ctx.__aenter__ = AsyncMock(return_value=session)
        session_ctx.__aexit__ = AsyncMock(return_value=None)
        session_begin_ctx = AsyncMock()
        session_begin_ctx.__aenter__ = AsyncMock(return_value=session_begin_ctx)
        session_begin_ctx.__aexit__ = AsyncMock(return_value=None)
        session.begin = MagicMock(return_value=session_begin_ctx)
        # first get → finding, second → None (client not found)
        session.get = AsyncMock(side_effect=[finding, None])
        app_state = _make_app_state(MagicMock(return_value=session_ctx))

        with structlog.testing.capture_logs() as cap:
            from app.reports.runner import draft_expedited

            await draft_expedited(1, app_state)

        warning_events = [e for e in cap if "not_found" in str(e.get("event", ""))]
        assert len(warning_events) >= 1


class TestDraftExpeditedHappyPath:
    @pytest.mark.asyncio
    async def test_creates_report_on_non_escalated_outcome(self):
        finding = MagicMock()
        finding.id = 1
        finding.client_id = 10
        finding.bucket = "urgent"

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

        app_state = _make_app_state(MagicMock(return_value=session_ctx))

        mock_report = MagicMock()
        mock_report.id = 42

        async def mock_run_agent(**kwargs):
            return {
                "escalated": False,
                "escalation_reason": None,
                "draft_result": {
                    "claims": [],
                    "draft_body": "test",
                    "corroboration_count": 1,
                    "corroboration_sources": [],
                },
                "followup_result": None,
            }

        async def mock_create_expedited(**kwargs):
            return mock_report

        import structlog.testing

        with structlog.testing.capture_logs() as cap:
            with patch("app.agent.graph.run_agent", side_effect=mock_run_agent):
                with patch("app.infra.modelserver_client.ModelserverClient"):
                    with patch(
                        "app.reports.runner.create_expedited_report",
                        side_effect=mock_create_expedited,
                    ):
                        from app.reports.runner import draft_expedited

                        await draft_expedited(1, app_state)

        complete_events = [e for e in cap if "complete" in str(e.get("event", ""))]
        assert len(complete_events) >= 1

    @pytest.mark.asyncio
    async def test_emergency_bucket_creates_followup(self):
        finding = MagicMock()
        finding.id = 2
        finding.client_id = 10
        finding.bucket = "emergency"

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

        app_state = _make_app_state(MagicMock(return_value=session_ctx))

        mock_report = MagicMock()
        mock_report.id = 99

        async def mock_run_agent(**kwargs):
            return {
                "escalated": False,
                "escalation_reason": None,
                "draft_result": {
                    "claims": [],
                    "draft_body": "emergency draft",
                    "corroboration_count": 1,
                    "corroboration_sources": [],
                },
                "followup_result": {"cover_message": "Emergency follow-up"},
            }

        create_followup_called = []

        async def mock_create_followup(**kwargs):
            create_followup_called.append(True)
            return MagicMock()

        with patch("app.agent.graph.run_agent", side_effect=mock_run_agent):
            with patch("app.infra.modelserver_client.ModelserverClient"):
                with patch(
                    "app.reports.runner.create_expedited_report",
                    side_effect=AsyncMock(return_value=mock_report),
                ):
                    with patch(
                        "app.reports.runner.create_followup",
                        side_effect=mock_create_followup,
                    ):
                        from app.reports.runner import draft_expedited

                        await draft_expedited(2, app_state)

        assert len(create_followup_called) == 1


class TestRedraftReport:
    @pytest.mark.asyncio
    async def test_report_not_found_logs_warning(self):
        import structlog.testing

        session_ctx = AsyncMock()
        session = AsyncMock()
        session_ctx.__aenter__ = AsyncMock(return_value=session)
        session_ctx.__aexit__ = AsyncMock(return_value=None)
        session_begin_ctx = AsyncMock()
        session_begin_ctx.__aenter__ = AsyncMock(return_value=session_begin_ctx)
        session_begin_ctx.__aexit__ = AsyncMock(return_value=None)
        session.begin = MagicMock(return_value=session_begin_ctx)
        session.get = AsyncMock(return_value=None)  # report not found

        app_state = _make_app_state(MagicMock(return_value=session_ctx))

        with structlog.testing.capture_logs() as cap:
            from app.reports.runner import redraft_report

            await redraft_report(report_id=999, comment="fix it", app_state=app_state)

        warning_events = [e for e in cap if "not_found" in str(e.get("event", ""))]
        assert len(warning_events) >= 1

    @pytest.mark.asyncio
    async def test_updates_report_fields_on_success(self):
        mock_report = MagicMock()
        mock_report.id = 1
        mock_report.client_id = 10
        mock_report.revision_count = 1
        mock_report.draft_body = "old body"

        mock_client = MagicMock()
        mock_client.id = 10

        mock_rf = MagicMock()
        mock_rf.finding_id = 5

        mock_finding = MagicMock()
        mock_finding.id = 5
        mock_finding.bucket = "urgent"

        session_ctx = AsyncMock()
        session = AsyncMock()
        session_ctx.__aenter__ = AsyncMock(return_value=session)
        session_ctx.__aexit__ = AsyncMock(return_value=None)
        session_begin_ctx = AsyncMock()
        session_begin_ctx.__aenter__ = AsyncMock(return_value=session_begin_ctx)
        session_begin_ctx.__aexit__ = AsyncMock(return_value=None)
        session.begin = MagicMock(return_value=session_begin_ctx)
        # get calls: report → client → finding
        session.get = AsyncMock(side_effect=[mock_report, mock_client, mock_finding])
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: mock_rf))

        app_state = _make_app_state(MagicMock(return_value=session_ctx))

        async def mock_run_agent(**kwargs):
            return {
                "escalated": False,
                "escalation_reason": None,
                "draft_result": {
                    "claims": [{"field": "Drug", "text": "Warfarin"}],
                    "draft_body": "new improved body",
                    "corroboration_count": 2,
                    "corroboration_sources": [],
                },
                "followup_result": None,
            }

        with patch("app.agent.graph.run_agent", side_effect=mock_run_agent):
            with patch("app.infra.modelserver_client.ModelserverClient"):
                from app.reports.runner import redraft_report

                await redraft_report(report_id=1, comment="needs improvement", app_state=app_state)

        assert mock_report.draft_body == "new improved body"
        assert mock_report.corroboration_count == 2

    @pytest.mark.asyncio
    async def test_escalation_path_emits_operator_alert(self):
        mock_report = MagicMock()
        mock_report.id = 1
        mock_report.client_id = 10
        mock_report.revision_count = 2
        mock_report.draft_body = "old"

        mock_client = MagicMock()
        mock_client.id = 10

        mock_rf = MagicMock()
        mock_rf.finding_id = 5

        mock_finding = MagicMock()
        mock_finding.id = 5
        mock_finding.client_id = 10
        mock_finding.bucket = "urgent"

        session_ctx = AsyncMock()
        session = AsyncMock()
        session_ctx.__aenter__ = AsyncMock(return_value=session)
        session_ctx.__aexit__ = AsyncMock(return_value=None)
        session_begin_ctx = AsyncMock()
        session_begin_ctx.__aenter__ = AsyncMock(return_value=session_begin_ctx)
        session_begin_ctx.__aexit__ = AsyncMock(return_value=None)
        session.begin = MagicMock(return_value=session_begin_ctx)
        session.get = AsyncMock(side_effect=[mock_report, mock_client, mock_finding])
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: mock_rf))

        persist_called = []

        async def mock_persist_alert(**kwargs):
            persist_called.append(kwargs["reason"])

        app_state = _make_app_state(MagicMock(return_value=session_ctx))

        async def mock_run_agent(**kwargs):
            return {
                "escalated": True,
                "escalation_reason": "ungroundable_no_evidence",
                "draft_result": None,
                "followup_result": None,
            }

        with patch("app.agent.graph.run_agent", side_effect=mock_run_agent):
            with patch("app.infra.modelserver_client.ModelserverClient"):
                with patch(
                    "app.reports.service.persist_operator_alert",
                    side_effect=mock_persist_alert,
                ):
                    from app.reports.runner import redraft_report

                    await redraft_report(report_id=1, comment="still broken", app_state=app_state)

        assert len(persist_called) == 1
        assert persist_called[0] == "ungroundable_no_evidence"
