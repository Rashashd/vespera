"""Persistence of agent output: expedited drafts, follow-up artifacts, operator alerts."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.domain.events import ReportDrafted, ReportOperatorAlert
from app.reports._helpers import now_utc
from app.reports.enums import FindingReportState, ReportStatus, ReportType
from app.reports.models import Report, ReportFinding, ReportFollowup
from app.triage.enums import FindingStatus
from app.triage.models import Finding

_log = structlog.get_logger(__name__)


async def create_expedited_report(
    *,
    finding: Finding,
    draft_outcome: dict,
    session: AsyncSession,
    settings: Settings,
    dispatcher: Any,
) -> Report:
    """Persist a grounded expedited draft and link the finding (idempotent, FR-030)."""
    # Idempotency: return existing active expedited report if one exists
    existing_rf = (
        await session.execute(
            select(ReportFinding)
            .join(Report, ReportFinding.report_id == Report.id)
            .where(
                ReportFinding.finding_id == finding.id,
                ReportFinding.report_type == ReportType.EXPEDITED,
                ReportFinding.state != FindingReportState.DISCARDED,
                Report.status.notin_([ReportStatus.DISCARDED, ReportStatus.APPROVED]),
            )
        )
    ).scalar_one_or_none()
    if existing_rf is not None:
        report = await session.get(Report, existing_rf.report_id)
        return report  # type: ignore[return-value]

    # No resurrection of terminal findings
    if finding.status == FindingStatus.DISCARDED:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="terminal_finding")

    sla_deadline = now_utc() + timedelta(hours=settings.expedited_sla_hours)

    report = Report(
        client_id=finding.client_id,
        report_type=ReportType.EXPEDITED,
        status=ReportStatus.DRAFTED,
        structured_fields=draft_outcome.get("claims", []),
        draft_body=draft_outcome.get("draft_body", ""),
        corroboration_count=draft_outcome.get("corroboration_count", 0),
        corroboration_sources=draft_outcome.get("corroboration_sources", []),
        revision_count=0,
        reviewer_comments=[],
        sla_deadline=sla_deadline,
        created_at=now_utc(),
        updated_at=now_utc(),
    )
    session.add(report)
    await session.flush()

    session.add(
        ReportFinding(
            report_id=report.id,
            finding_id=finding.id,
            client_id=finding.client_id,
            report_type=ReportType.EXPEDITED,
            state=FindingReportState.INCLUDED,
            created_at=now_utc(),
        )
    )

    # Claim finding: pending_expedited → processing
    finding.status = FindingStatus.PROCESSING
    finding.updated_at = now_utc()

    await dispatcher.dispatch(
        ReportDrafted(
            actor_id=0,
            actor_type="system",
            client_id=finding.client_id,
            report_id=report.id,
            report_type=ReportType.EXPEDITED,
        ),
        session,
    )
    return report


async def create_followup(
    *,
    finding: Finding,
    report: Report,
    followup_result: dict,
    session: AsyncSession,
) -> ReportFollowup:
    """Persist the emergency follow-up artifact (idempotent via unique index)."""
    existing = (
        await session.execute(select(ReportFollowup).where(ReportFollowup.finding_id == finding.id))
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    followup = ReportFollowup(
        client_id=finding.client_id,
        finding_id=finding.id,
        report_id=report.id,
        template_ref=followup_result.get("template_ref", "emergency_author_outreach_v1"),
        cover_message=followup_result.get("cover_message", ""),
        recipient_kind="author",
        status="generated",
        created_at=now_utc(),
    )
    session.add(followup)
    return followup


async def persist_operator_alert(
    *,
    finding: Finding,
    reason: str,
    session: AsyncSession,
    dispatcher: Any,
) -> None:
    """Emit ReportOperatorAlert event (no report row; FR-025/026)."""
    _log.warning(
        "report.operator_alert",
        client_id=finding.client_id,
        finding_id=finding.id,
        reason=reason,
    )
    await dispatcher.dispatch(
        ReportOperatorAlert(
            actor_id=0,
            actor_type="system",
            client_id=finding.client_id,
            finding_id=finding.id,
            reason=reason,
        ),
        session,
    )
