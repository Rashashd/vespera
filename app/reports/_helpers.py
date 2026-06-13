"""Shared internal helpers for report persistence and HITL transitions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.domain.events import ReportDiscarded
from app.reports.enums import FindingReportState, ReportStatus, ReportType
from app.reports.models import Report, ReportFinding
from app.triage.enums import FindingStatus
from app.triage.models import Finding

# Statuses a report may be in for a reviewer action to apply (before terminal).
REVIEW_STATUSES = {ReportStatus.DRAFTED, ReportStatus.UNDER_REVIEW}


def now_utc() -> datetime:
    return datetime.now(UTC)


async def load_report_for_client(report_id: int, client_id: int, session: AsyncSession) -> Report:
    report = await session.get(Report, report_id)
    if report is None or report.client_id != client_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="REPORT_NOT_FOUND")
    return report


async def load_report_finding(
    report_id: int, finding_id: int, client_id: int, session: AsyncSession
) -> ReportFinding:
    row = (
        await session.execute(
            select(ReportFinding).where(
                ReportFinding.report_id == report_id,
                ReportFinding.finding_id == finding_id,
                ReportFinding.client_id == client_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="REPORT_FINDING_NOT_FOUND")
    return row


async def mark_expedited_finding_reported(report: Report, session: AsyncSession) -> None:
    """For expedited reports: flip the linked finding to 'reported'."""
    if report.report_type != ReportType.EXPEDITED:
        return
    rf = (
        await session.execute(
            select(ReportFinding).where(
                ReportFinding.report_id == report.id,
                ReportFinding.report_type == ReportType.EXPEDITED,
            )
        )
    ).scalar_one_or_none()
    if rf is not None:
        finding = await session.get(Finding, rf.finding_id)
        if finding:
            finding.status = FindingStatus.REPORTED
            finding.updated_at = now_utc()


async def maybe_auto_discard_batch(
    report_id: int,
    client_id: int,
    reviewer: User,
    session: AsyncSession,
    dispatcher: Any,
) -> None:
    """Auto-discard the batch report if no included findings remain (FR-013a)."""
    included = (
        (
            await session.execute(
                select(ReportFinding).where(
                    ReportFinding.report_id == report_id,
                    ReportFinding.state == FindingReportState.INCLUDED,
                )
            )
        )
        .scalars()
        .all()
    )
    if included:
        return
    report = await session.get(Report, report_id)
    if report and not ReportStatus(report.status).is_terminal:
        report.status = ReportStatus.DISCARDED
        report.updated_at = now_utc()
        await dispatcher.dispatch(
            ReportDiscarded(
                actor_id=reviewer.id,
                actor_type="human",
                client_id=client_id,
                report_id=report_id,
                report_type=report.report_type,
            ),
            session,
        )
