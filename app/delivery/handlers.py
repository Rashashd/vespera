"""Passive domain-event handlers wiring approval/reactivation to durable delivery jobs."""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dispatcher import EventDispatcher
from app.domain.events import ClientReactivated, ReportApproved
from app.jobs.enqueue import enqueue
from app.reports.enums import ReportStatus
from app.reports.models import Report

_log = structlog.get_logger(__name__)


def make_on_report_approved(app: Any):
    """Build the ReportApproved handler bound to the app (for the ARQ enqueue connection).

    HITL gate: delivery is enqueued ONLY here, never dispatched inline from the approve route.
    Deterministic job_id keeps re-approval / retry idempotent; the job re-checks `approved`
    status at send time so an enqueue from a rolled-back txn is a safe no-op.
    """

    async def on_report_approved(event: ReportApproved, session: AsyncSession) -> None:
        await enqueue(
            "task_deliver_report",
            job_id=f"deliver:{event.report_id}",
            app_state=app.state,
            report_id=event.report_id,
        )
        _log.info("delivery.enqueued_on_approval", report_id=event.report_id)

    return on_report_approved


def make_on_client_reactivated(app: Any):
    """Build the ClientReactivated handler: re-enqueue delivery for the client's held reports.

    A report held by suspension stays `approved`; on reactivation re-enqueue each approved
    report. The delivery job is idempotent and re-checks status, so this never double-sends.
    """

    async def on_client_reactivated(event: ClientReactivated, session: AsyncSession) -> None:
        client_id = event.target_client_id
        report_ids = (
            (
                await session.execute(
                    select(Report.id).where(
                        Report.client_id == client_id,
                        Report.status == ReportStatus.APPROVED.value,
                    )
                )
            )
            .scalars()
            .all()
        )
        for report_id in report_ids:
            await enqueue(
                "task_deliver_report",
                job_id=f"deliver:{report_id}",
                app_state=app.state,
                report_id=report_id,
            )
        if report_ids:
            _log.info("delivery.reactivation_release", client_id=client_id, count=len(report_ids))

    return on_client_reactivated


def register_delivery_handlers(dispatcher: EventDispatcher, app: Any) -> None:
    """Register the approval + reactivation delivery handlers on the API dispatcher."""
    dispatcher.register(ReportApproved, make_on_report_approved(app))
    dispatcher.register(ClientReactivated, make_on_client_reactivated(app))
