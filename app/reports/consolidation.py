"""Batch report consolidation: select pending_batch findings via document_watchlists."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.events import BatchConsolidated, ReportDrafted
from app.ingestion.models import DocumentWatchlist
from app.reports.enums import FindingReportState, ReportStatus, ReportType
from app.reports.models import Report, ReportFinding
from app.triage.enums import FindingStatus
from app.triage.models import Finding

_log = structlog.get_logger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


async def consolidate_batch(
    *,
    watchlist_id: int,
    client_id: int,
    cycle_period_start: datetime,
    cycle_period_end: datetime,
    session: AsyncSession,
    dispatcher: Any,
) -> Report | None:
    """Consolidate pending_batch findings for watchlist W into one batch report.

    Returns the Report if findings exist, or None if none to consolidate (FR-013).
    Idempotent via ux_reports_batch_cycle partial unique (SC-008).
    First watchlist to claim wins (research D2).
    """
    log = _log.bind(watchlist_id=watchlist_id, client_id=client_id)

    # Check for existing active batch report for this cycle (idempotency)
    existing = (
        await session.execute(
            select(Report).where(
                Report.watchlist_id == watchlist_id,
                Report.cycle_period_start == cycle_period_start,
                Report.report_type == ReportType.BATCH,
                Report.status.notin_([ReportStatus.APPROVED, ReportStatus.DISCARDED]),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        log.info("consolidate.already_exists", report_id=existing.id)
        return existing

    # Select document_ids in this watchlist via the junction table
    doc_ids_result = (
        (
            await session.execute(
                select(DocumentWatchlist.document_id).where(
                    DocumentWatchlist.watchlist_id == watchlist_id,
                    DocumentWatchlist.client_id == client_id,
                )
            )
        )
        .scalars()
        .all()
    )

    if not doc_ids_result:
        log.info("consolidate.no_documents")
        return None

    doc_ids = list(doc_ids_result)

    # Find pending_batch findings whose document is in this watchlist
    findings = (
        (
            await session.execute(
                select(Finding).where(
                    Finding.client_id == client_id,
                    Finding.document_id.in_(doc_ids),
                    Finding.status == FindingStatus.PENDING_BATCH,
                )
            )
        )
        .scalars()
        .all()
    )

    if not findings:
        log.info("consolidate.no_pending_findings")
        return None

    # Build the batch report
    finding_count = len(findings)
    structured_fields = _build_batch_structured_fields(findings)
    draft_body = _build_batch_draft_body(findings, watchlist_id, cycle_period_start)

    report = Report(
        client_id=client_id,
        report_type=ReportType.BATCH,
        status=ReportStatus.DRAFTED,
        structured_fields=structured_fields,
        draft_body=draft_body,
        corroboration_count=_count_unique_documents(findings),
        corroboration_sources=[],
        revision_count=0,
        reviewer_comments=[],
        watchlist_id=watchlist_id,
        cycle_period_start=cycle_period_start,
        cycle_period_end=cycle_period_end,
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(report)
    await session.flush()

    # Idempotently claim findings: flip status → reported + create report_findings
    for finding in findings:
        finding.status = FindingStatus.REPORTED
        finding.updated_at = _now()
        session.add(
            ReportFinding(
                report_id=report.id,
                finding_id=finding.id,
                client_id=client_id,
                report_type=ReportType.BATCH,
                state=FindingReportState.INCLUDED,
                created_at=_now(),
            )
        )

    await dispatcher.dispatch(
        ReportDrafted(
            actor_id=0,
            actor_type="system",
            client_id=client_id,
            report_id=report.id,
            report_type=ReportType.BATCH,
        ),
        session,
    )
    await dispatcher.dispatch(
        BatchConsolidated(
            actor_id=0,
            actor_type="system",
            client_id=client_id,
            watchlist_id=watchlist_id,
            report_id=report.id,
        ),
        session,
    )
    log.info("consolidate.done", report_id=report.id, finding_count=finding_count)
    return report


def _build_batch_structured_fields(findings: list[Finding]) -> list[dict]:
    """Build a claim list, split into positive and minor sections, grouped by reaction (FR-012).

    Batch summary lines aggregate already-grounded findings, so they carry the
    `aggregated` provenance (no single source passage) and are exempt from the
    per-claim grounding gate (SC-001 covers machine-drafted, passage-grounded claims).
    """
    claims: list[dict] = []
    for bucket_value, section in (
        ("positive", "Positive findings"),
        ("minor", "Minor adverse events"),
    ):
        group_findings = [f for f in findings if f.bucket == bucket_value]
        by_reaction: dict[str, list[Finding]] = {}
        for f in group_findings:
            by_reaction.setdefault(f.reaction, []).append(f)
        for reaction, group in by_reaction.items():
            drugs = sorted({f.drug for f in group})
            claims.append(
                {
                    "field": "Reaction",
                    "section": section,
                    "text": f"{reaction} reported for: {', '.join(drugs)} ({len(group)} findings)",
                    "provenance": "aggregated",
                    "source_ref": None,
                }
            )
    return claims


def _build_batch_draft_body(
    findings: list[Finding], watchlist_id: int, cycle_start: datetime
) -> str:
    """Render a short batch report narrative."""
    bucket_counts: dict[str, int] = {}
    for f in findings:
        bucket_counts[f.bucket] = bucket_counts.get(f.bucket, 0) + 1

    summary_parts = [f"{count} {bucket}" for bucket, count in sorted(bucket_counts.items())]
    cycle_str = cycle_start.strftime("%Y-%m-%d")
    return (
        f"Batch safety report for watchlist {watchlist_id} — cycle starting {cycle_str}.\n"
        f"Findings: {', '.join(summary_parts)}.\n"
        f"Total: {len(findings)} findings across {_count_unique_documents(findings)} documents."
    )


def _count_unique_documents(findings: list[Finding]) -> int:
    return len({f.document_id for f in findings})
