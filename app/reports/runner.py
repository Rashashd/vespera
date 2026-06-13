"""In-process expedited drafting trigger (commit-then-BackgroundTasks, per bg-tasks memory)."""

from __future__ import annotations

import structlog

from app.reports.service import create_expedited_report, create_followup, persist_operator_alert
from app.triage.enums import Bucket
from app.triage.models import Finding

_log = structlog.get_logger(__name__)


async def draft_expedited(finding_id: int, app_state: object) -> None:
    """Draft an expedited report for a finding; invoked via BackgroundTasks after commit.

    Shape kept simple so spec-11 ARQ can enqueue it unchanged.
    """
    settings = app_state.settings  # type: ignore[attr-defined]
    session_factory = app_state.session_factory  # type: ignore[attr-defined]
    redis = app_state.redis  # type: ignore[attr-defined]
    dispatcher = app_state.dispatcher  # type: ignore[attr-defined]

    log = _log.bind(finding_id=finding_id)

    async with session_factory() as session:
        async with session.begin():
            finding = await session.get(Finding, finding_id)
            if finding is None:
                log.warning("draft_expedited.finding_not_found")
                return

            # Import client model here to avoid circular at module load
            from app.clients.models import Client

            client = await session.get(Client, finding.client_id)
            if client is None:
                log.warning("draft_expedited.client_not_found", client_id=finding.client_id)
                return

            # Build the modelserver client for retrieval (must be entered so its HTTP client exists)
            from app.agent.graph import run_agent
            from app.infra.modelserver_client import ModelserverClient

            log.info(
                "draft_expedited.start",
                client_id=finding.client_id,
                bucket=finding.bucket,
            )
            async with ModelserverClient.from_settings(settings) as ms_client:
                outcome = await run_agent(
                    finding=finding,
                    client=client,
                    session=session,
                    redis=redis,
                    ms_client=ms_client,
                    app_state=app_state,
                    settings=settings,
                )

            if outcome["escalated"]:
                await persist_operator_alert(
                    finding=finding,
                    reason=outcome["escalation_reason"],
                    session=session,
                    dispatcher=dispatcher,
                )
                return

            report = await create_expedited_report(
                finding=finding,
                draft_outcome=outcome["draft_result"],
                session=session,
                settings=settings,
                dispatcher=dispatcher,
            )

            # Emergency findings MUST get a follow-up artifact (FR-006) — deterministic, not
            # contingent on the agent choosing to call draft_followup (it is a fixed template).
            if finding.bucket == Bucket.EMERGENCY:
                followup_result = outcome.get("followup_result") or {
                    "template_ref": "emergency_author_outreach_v1",
                    "cover_message": (
                        f"A life-threatening adverse event has been identified: {finding.drug} "
                        f"associated with {finding.reaction}. Please complete and return the "
                        f"attached reporting form."
                    ),
                }
                await create_followup(
                    finding=finding,
                    report=report,
                    followup_result=followup_result,
                    session=session,
                )

            log.info("draft_expedited.complete", report_id=report.id)


async def redraft_report(
    *,
    report_id: int,
    comment: str,
    app_state: object,
) -> None:
    """Redraft a report after reviewer rejection; invoked via BackgroundTasks after commit."""
    from sqlalchemy import select

    from app.reports.models import Report, ReportFinding
    from app.reports.service import persist_operator_alert

    settings = app_state.settings  # type: ignore[attr-defined]
    session_factory = app_state.session_factory  # type: ignore[attr-defined]
    redis = app_state.redis  # type: ignore[attr-defined]
    dispatcher = app_state.dispatcher  # type: ignore[attr-defined]

    log = _log.bind(report_id=report_id)

    async with session_factory() as session:
        async with session.begin():
            report = await session.get(Report, report_id)
            if report is None:
                log.warning("redraft.report_not_found")
                return

            from app.clients.models import Client

            client = await session.get(Client, report.client_id)
            if client is None:
                log.warning("redraft.client_not_found")
                return

            # Get the linked finding for this expedited report
            rf = (
                await session.execute(
                    select(ReportFinding).where(ReportFinding.report_id == report_id)
                )
            ).scalar_one_or_none()
            if rf is None:
                log.warning("redraft.no_report_finding")
                return

            from app.triage.models import Finding

            finding = await session.get(Finding, rf.finding_id)
            if finding is None:
                log.warning("redraft.finding_not_found")
                return

            from app.agent.graph import run_agent
            from app.infra.modelserver_client import ModelserverClient

            log.info("redraft.start", revision_count=report.revision_count)
            async with ModelserverClient.from_settings(settings) as ms_client:
                outcome = await run_agent(
                    finding=finding,
                    client=client,
                    session=session,
                    redis=redis,
                    ms_client=ms_client,
                    app_state=app_state,
                    settings=settings,
                    prior_draft_body=report.draft_body or "",
                    redraft_comment=comment,
                )

            if outcome["escalated"]:
                await persist_operator_alert(
                    finding=finding,
                    reason=outcome["escalation_reason"],
                    session=session,
                    dispatcher=dispatcher,
                )
                return

            # Update report in-place with new draft
            dr = outcome["draft_result"]
            report.structured_fields = dr.get("claims", [])
            report.draft_body = dr.get("draft_body", "")
            report.corroboration_count = dr.get("corroboration_count", 0)
            report.corroboration_sources = dr.get("corroboration_sources", [])

            from datetime import UTC, datetime

            report.updated_at = datetime.now(UTC)
            log.info("redraft.complete", report_id=report_id)
