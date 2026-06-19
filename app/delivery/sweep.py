"""Periodic sweep: flip no-callback timeouts to failed and escalate overdue reviewer deadlines."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select

from app.delivery.n8n_client import N8nClient
from app.delivery.notifications import notify_delivery_failure, notify_sla_escalation
from app.delivery.service import mark_no_callback_failed
from app.domain.events import SlaEscalated
from app.reports.enums import ReportStatus, ReportType
from app.reports.models import Report

_log = structlog.get_logger(__name__)
_SYSTEM_ACTOR_ID = 0

# An expedited report is still "open" (un-actioned) only in these review states.
_OPEN_REVIEW = [
    ReportStatus.DRAFTED.value,
    ReportStatus.UNDER_REVIEW.value,
    ReportStatus.NEEDS_MANUAL_REVISION.value,
]


def _aware(dt: datetime) -> datetime:
    """Normalize a possibly-naive timestamp to UTC-aware for comparison."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


async def run_sla_sweep(wc: Any, *, now: datetime | None = None) -> dict:
    """One sweep pass: no-callback timeout flips + tiered SLA escalation (FR-006a/FR-012).

    - `sent` reports whose `sent_at` predates the no-callback window → delivery_failed + alert.
    - Open expedited reports past `sla_deadline` escalate Tier-1 (reviewers), then — after the
      Tier-2 interval still un-actioned — Tier-2 (manager/admin). Each tier fires at most once;
      an actioned report (no longer in a review state) is excluded and never escalates.
    """
    n8n = N8nClient.from_settings(wc.settings)
    now = now or datetime.now(UTC)
    window = timedelta(hours=wc.settings.delivery_no_callback_window_hours)
    tier2_gap = timedelta(hours=wc.settings.sla_tier2_interval_hours)
    result = {"timed_out": 0, "tier1": 0, "tier2": 0}

    async with wc.session_factory() as session:
        async with session.begin():
            # 1. No-callback timeout.
            cutoff = now - window
            stale = (
                (
                    await session.execute(
                        select(Report).where(
                            Report.status == ReportStatus.SENT.value,
                            Report.sent_at.is_not(None),
                            Report.sent_at < cutoff,
                        )
                    )
                )
                .scalars()
                .all()
            )
            for report in stale:
                await mark_no_callback_failed(session, report, wc.dispatcher)
                await notify_delivery_failure(
                    session,
                    n8n,
                    report_id=report.id,
                    client_id=report.client_id,
                    reason="no_callback",
                )
                result["timed_out"] += 1

            # 2. Tiered SLA escalation on open expedited reports.
            open_exp = (
                (
                    await session.execute(
                        select(Report).where(
                            Report.report_type == ReportType.EXPEDITED.value,
                            Report.status.in_(_OPEN_REVIEW),
                            Report.sla_deadline.is_not(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for report in open_exp:
                deadline = _aware(report.sla_deadline)
                tier: int | None = None
                if report.sla_escalation_tier == 0 and now > deadline:
                    tier = 1
                elif (
                    report.sla_escalation_tier == 1
                    and report.sla_escalated_at is not None
                    and now > _aware(report.sla_escalated_at) + tier2_gap
                ):
                    tier = 2
                if tier is None:
                    continue
                report.sla_escalation_tier = tier
                report.sla_escalated_at = now
                report.updated_at = now
                await wc.dispatcher.dispatch(
                    SlaEscalated(
                        actor_id=_SYSTEM_ACTOR_ID,
                        actor_type="system",
                        client_id=report.client_id,
                        report_id=report.id,
                        tier=tier,
                    ),
                    session,
                )
                await notify_sla_escalation(
                    session, n8n, report_id=report.id, client_id=report.client_id, tier=tier
                )
                result[f"tier{tier}"] += 1

    _log.info("delivery.sla_sweep", **result)
    return result
