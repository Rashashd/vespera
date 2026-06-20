"""Reviewer HITL actions, consolidation trigger, and queue/detail read routes (spec 9)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import acting_client, require_reviewer, require_staff
from app.auth.models import User
from app.clients.models import Client
from app.core.dependencies import get_session
from app.jobs.enqueue import enqueue
from app.reports import service as svc
from app.reports.enums import ReportStatus
from app.reports.models import Report
from app.reports.schemas import (
    DiscardRequest,
    EditApproveRequest,
    FindingDiscardRequest,
    RejectRequest,
    ReportResponse,
    ReportSummary,
)
from app.triage.models import Finding

router = APIRouter(prefix="/clients/{client_id}", tags=["reports"])

_get_client = acting_client()
_get_client_read = acting_client(allow_suspended=True)


def _now() -> datetime:
    return datetime.now(UTC)


# ── Queue & detail reads ─────────────────────────────────────────────────────

_REVIEW_STATUSES = {
    ReportStatus.DRAFTED,
    ReportStatus.UNDER_REVIEW,
    ReportStatus.NEEDS_MANUAL_REVISION,
}


@router.get("/reports", response_model=list[ReportSummary])
async def list_reports(
    request: Request,
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    reviewer: User = Depends(require_reviewer),
    client: Client = Depends(_get_client_read),
    session: AsyncSession = Depends(get_session),
) -> list[ReportSummary]:
    """Return the reviewer queue (drafted/under_review/needs_manual_revision reports only)."""
    q = (
        select(Report)
        .where(Report.client_id == client.id)
        .order_by(Report.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if status == "all":
        pass  # no filter — return every status (FR-006a all-reports view)
    elif status:
        q = q.where(Report.status == status)
    else:
        q = q.where(Report.status.in_([s.value for s in _REVIEW_STATUSES]))

    rows = (await session.execute(q)).scalars().all()
    return [ReportSummary.model_validate(r) for r in rows]


@router.get("/reports/{report_id}", response_model=ReportResponse)
async def get_report(
    report_id: int,
    reviewer: User = Depends(require_reviewer),
    client: Client = Depends(_get_client_read),
    session: AsyncSession = Depends(get_session),
) -> ReportResponse:
    """Return the full report including all citation sources (FR-020)."""
    report = await session.get(Report, report_id)
    if report is None or report.client_id != client.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="REPORT_NOT_FOUND")
    return ReportResponse.model_validate(report)


# ── HITL actions ─────────────────────────────────────────────────────────────


@router.post("/reports/{report_id}/approve", response_model=ReportSummary)
async def approve_report(
    request: Request,
    report_id: int,
    reviewer: User = Depends(require_reviewer),
    client: Client = Depends(_get_client),
    session: AsyncSession = Depends(get_session),
) -> ReportSummary:
    """Approve a report: drafted|under_review → approved."""
    # The transaction is owned by get_session; opening another here would double-begin.
    report = await svc.approve_report(
        report_id=report_id,
        client_id=client.id,
        reviewer=reviewer,
        session=session,
        dispatcher=request.app.state.dispatcher,
    )
    return ReportSummary.model_validate(report)


@router.post("/reports/{report_id}/edit-approve", response_model=ReportSummary)
async def edit_approve_report(
    request: Request,
    report_id: int,
    body: EditApproveRequest,
    reviewer: User = Depends(require_reviewer),
    client: Client = Depends(_get_client),
    session: AsyncSession = Depends(get_session),
) -> ReportSummary:
    """Edit report content then approve (reviewer_attested provenance)."""
    report = await svc.edit_approve_report(
        report_id=report_id,
        client_id=client.id,
        reviewer=reviewer,
        draft_body=body.draft_body,
        structured_fields=[c.model_dump() for c in body.structured_fields],
        comment=body.comment,
        session=session,
        dispatcher=request.app.state.dispatcher,
        settings=request.app.state.settings,
    )
    return ReportSummary.model_validate(report)


@router.post("/reports/{report_id}/reject", response_model=ReportSummary)
async def reject_report(
    request: Request,
    report_id: int,
    body: RejectRequest,
    reviewer: User = Depends(require_reviewer),
    client: Client = Depends(_get_client),
    session: AsyncSession = Depends(get_session),
) -> ReportSummary:
    """Reject and trigger redraft (or needs_manual_revision on 4th rejection)."""
    settings = request.app.state.settings
    report = await svc.reject_report(
        report_id=report_id,
        client_id=client.id,
        reviewer=reviewer,
        comment=body.comment,
        redraft_cap=settings.report_redraft_cap,
        session=session,
        dispatcher=request.app.state.dispatcher,
        settings=settings,
    )

    if ReportStatus(report.status) == ReportStatus.DRAFTED:
        await enqueue(
            "task_redraft",
            job_id=f"redraft:{report_id}:{report.revision_count}",
            app_state=request.app.state,
            report_id=report_id,
            revision=report.revision_count,
            comment=body.comment,
        )

    return ReportSummary.model_validate(report)


@router.post("/reports/{report_id}/discard", response_model=ReportSummary)
async def discard_report(
    request: Request,
    report_id: int,
    body: DiscardRequest,
    reviewer: User = Depends(require_reviewer),
    client: Client = Depends(_get_client),
    session: AsyncSession = Depends(get_session),
) -> ReportSummary:
    """Discard a report (terminal)."""
    report = await svc.discard_report(
        report_id=report_id,
        client_id=client.id,
        reviewer=reviewer,
        session=session,
        dispatcher=request.app.state.dispatcher,
    )
    return ReportSummary.model_validate(report)


# ── Per-finding actions in batch reports ──────────────────────────────────────


@router.post("/reports/{report_id}/findings/{finding_id}/drop", status_code=204)
async def drop_finding(
    request: Request,
    report_id: int,
    finding_id: int,
    reviewer: User = Depends(require_reviewer),
    client: Client = Depends(_get_client),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Drop a finding back to pending_batch (re-eligible next cycle)."""
    await svc.drop_finding_from_report(
        report_id=report_id,
        finding_id=finding_id,
        client_id=client.id,
        reviewer=reviewer,
        session=session,
        dispatcher=request.app.state.dispatcher,
    )


@router.post("/reports/{report_id}/findings/{finding_id}/discard", status_code=204)
async def discard_finding(
    request: Request,
    report_id: int,
    finding_id: int,
    body: FindingDiscardRequest,
    reviewer: User = Depends(require_reviewer),
    client: Client = Depends(_get_client),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Permanently discard a finding from a batch report."""
    await svc.discard_finding_permanently(
        report_id=report_id,
        finding_id=finding_id,
        client_id=client.id,
        reviewer=reviewer,
        session=session,
        dispatcher=request.app.state.dispatcher,
    )


# ── Batch consolidation ───────────────────────────────────────────────────────


@router.post("/watchlists/{watchlist_id}/consolidate-batch", status_code=status.HTTP_202_ACCEPTED)
async def consolidate_batch_route(
    request: Request,
    watchlist_id: int,
    cycle_start: datetime = Query(..., description="Cycle period start (ISO-8601)"),
    cycle_end: datetime = Query(..., description="Cycle period end (ISO-8601)"),
    staff: User = Depends(require_staff),
    client: Client = Depends(_get_client),
) -> dict:
    """Enqueue batch consolidation for a watchlist cycle (202 — FR-001/G1).

    Note: API contract changed from sync (returns Report) to async (202 enqueue).
    Forward dependency: spec-10 admin console consolidate trigger must account for this.
    """
    period_start_iso = cycle_start.isoformat()
    period_end_iso = cycle_end.isoformat()
    job_id = f"consolidate:manual:{watchlist_id}:{period_start_iso}"

    await enqueue(
        "task_consolidate",
        job_id=job_id,
        app_state=request.app.state,
        watchlist_id=watchlist_id,
        client_id=client.id,
        cycle_period_start=period_start_iso,
        cycle_period_end=period_end_iso,
        cycle_id=None,
    )
    return {"status": "accepted", "job_id": job_id}


# ── Admin re-trigger for expedited draft ─────────────────────────────────────


@router.post("/findings/{finding_id}/draft", response_model=ReportSummary)
async def retrigger_expedited_draft(
    request: Request,
    finding_id: int,
    staff: User = Depends(require_staff),
    client: Client = Depends(_get_client),
    session: AsyncSession = Depends(get_session),
) -> ReportSummary:
    """Admin: (re)draft the expedited report for a finding (idempotent, FR-030).

    Returns existing active report if one exists. Returns 409 for terminal findings.
    """
    finding = await session.get(Finding, finding_id)
    if finding is None or finding.client_id != client.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="FINDING_NOT_FOUND")

    from app.triage.enums import Bucket

    if finding.bucket not in (Bucket.URGENT, Bucket.EMERGENCY):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="NOT_EXPEDITED_BUCKET")

    if finding.status == "discarded":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="terminal_finding")

    from app.reports.models import ReportFinding as RF

    existing_rf = (
        await session.execute(
            select(RF)
            .join(Report, RF.report_id == Report.id)
            .where(
                RF.finding_id == finding_id,
                RF.report_type == "expedited",
                RF.state != "discarded",
                Report.status.notin_(["approved", "discarded"]),
            )
        )
    ).scalar_one_or_none()

    if existing_rf is not None:
        report = await session.get(Report, existing_rf.report_id)
        return ReportSummary.model_validate(report)

    await enqueue(
        "task_expedited",
        job_id=f"expedited:{finding_id}:0",
        app_state=request.app.state,
        finding_id=finding_id,
        revision=0,
    )
    raise HTTPException(status.HTTP_202_ACCEPTED, detail="draft_scheduled")
