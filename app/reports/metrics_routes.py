"""Operations-dashboard metrics endpoint (FR-021a): GET /clients/{id}/metrics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import acting_client, require_admin
from app.auth.models import User
from app.clients.models import Client
from app.core.dependencies import get_session
from app.observability.schemas import OpsDashboard, QueueMetrics, RedraftMetrics, SlaMetrics
from app.reports.enums import ReportStatus, ReportType
from app.reports.models import Report

router = APIRouter(prefix="/clients/{client_id}", tags=["metrics"])

_get_client_read = acting_client(allow_suspended=True)

_TERMINAL = {ReportStatus.APPROVED.value, ReportStatus.REJECTED.value, ReportStatus.DISCARDED.value}
_NON_TERMINAL = {
    ReportStatus.DRAFTED.value,
    ReportStatus.UNDER_REVIEW.value,
    ReportStatus.NEEDS_MANUAL_REVISION.value,
}
_DUE_SOON_HOURS = 2


@router.get("/metrics", response_model=OpsDashboard)
async def get_ops_metrics(
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None),
    admin: User = Depends(require_admin),
    client: Client = Depends(_get_client_read),
    session: AsyncSession = Depends(get_session),
) -> OpsDashboard:
    """Live operational KPIs from reports/findings (delivery block is null — spec-13 dependency)."""
    now = datetime.now(UTC)

    q = select(Report).where(Report.client_id == client.id)
    if from_:
        q = q.where(Report.created_at >= from_)
    if to:
        q = q.where(Report.created_at <= to)

    reports = (await session.execute(q)).scalars().all()

    # by_status
    by_status: dict[str, int] = {}
    for r in reports:
        by_status[r.status] = by_status.get(r.status, 0) + 1

    # queue (non-terminal)
    non_term = [r for r in reports if r.status in _NON_TERMINAL]
    expedited = sum(1 for r in non_term if r.report_type == ReportType.EXPEDITED.value)
    batch = sum(1 for r in non_term if r.report_type == ReportType.BATCH.value)

    # sla (on expedited reports only)
    exp_reports = [r for r in non_term if r.report_type == ReportType.EXPEDITED.value]
    overdue = sum(
        1 for r in exp_reports if r.sla_deadline and r.sla_deadline.replace(tzinfo=UTC) < now
    )
    due_soon = sum(
        1
        for r in exp_reports
        if r.sla_deadline
        and now <= r.sla_deadline.replace(tzinfo=UTC) < now + timedelta(hours=_DUE_SOON_HOURS)
    )
    total_exp = len(exp_reports)
    met = total_exp - overdue - due_soon
    met_pct = round(100.0 * met / total_exp, 1) if total_exp else 100.0

    # redraft
    all_revisions = [r.revision_count for r in reports]
    avg_rev = sum(all_revisions) / len(all_revisions) if all_revisions else 0.0
    hit_cap = sum(1 for r in reports if r.status == ReportStatus.NEEDS_MANUAL_REVISION.value)

    return OpsDashboard(
        client_id=client.id,
        by_status=by_status,
        queue=QueueMetrics(pending=len(non_term), expedited=expedited, batch=batch),
        sla=SlaMetrics(overdue=overdue, due_soon=due_soon, met_pct=met_pct),
        redraft=RedraftMetrics(avg_revisions=round(avg_rev, 2), hit_cap=hit_cap),
        delivery=None,
        window={"from": from_.isoformat() if from_ else None, "to": to.isoformat() if to else None},
    )
