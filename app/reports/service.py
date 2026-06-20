"""Public facade for report operations — re-exports from drafting/ and review/.

Implementation lives in:
- app/reports/drafting.py  — create_expedited_report, create_followup, persist_operator_alert
- app/reports/review.py    — approve/edit/reject/discard + per-finding drop/discard
- app/reports/_helpers.py  — shared load/transition helpers
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.reports.drafting import (
    create_expedited_report,
    create_followup,
    persist_operator_alert,
)
from app.reports.models import ReportFinding
from app.reports.review import (
    approve_report,
    discard_finding_permanently,
    discard_report,
    drop_finding_from_report,
    edit_approve_report,
    reject_report,
)
from app.triage.models import Finding

# Severity ordering used to pick a report's headline bucket from its included findings.
_BUCKET_RANK = {"emergency": 4, "urgent": 3, "minor": 2, "positive": 1, "irrelevant": 0}


async def severity_by_report(session: AsyncSession, report_ids: list[int]) -> dict[int, str]:
    """Map report_id → highest-severity included-finding bucket (single query; empty-safe)."""
    if not report_ids:
        return {}
    rows = (
        await session.execute(
            select(ReportFinding.report_id, Finding.bucket)
            .join(Finding, Finding.id == ReportFinding.finding_id)
            .where(
                ReportFinding.report_id.in_(report_ids),
                ReportFinding.state == "included",
            )
        )
    ).all()
    out: dict[int, str] = {}
    for report_id, bucket in rows:
        if report_id not in out or _BUCKET_RANK.get(bucket, 0) > _BUCKET_RANK.get(
            out[report_id], 0
        ):
            out[report_id] = bucket
    return out


__all__ = [
    "create_expedited_report",
    "create_followup",
    "persist_operator_alert",
    "approve_report",
    "edit_approve_report",
    "reject_report",
    "discard_report",
    "drop_finding_from_report",
    "discard_finding_permanently",
    "severity_by_report",
]
