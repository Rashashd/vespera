"""Reviewer HITL actions, consolidation trigger, and queue/detail read routes (spec 9)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import acting_client, require_reviewer, require_staff
from app.auth.models import User
from app.clients.models import Client
from app.core.dependencies import get_session
from app.reports import service as svc
from app.reports.consolidation import consolidate_batch
from app.reports.enums import ReportStatus
from app.reports.models import Report, ReportFinding
from app.reports.schemas import (
    ConsolidateResponse,
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
    async with session.begin():
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
    async with session.begin():
        report = await svc.edit_approve_report(
            report_id=report_id,
            client_id=client.id,
            reviewer=reviewer,
            draft_body=body.draft_body,
            structured_fields=[c.model_dump() for c in body.structured_fields],
            comment=body.comment,
            session=session,
            dispatcher=request.app.state.dispatcher,
        )
    return ReportSummary.model_validate(report)


@router.post("/reports/{report_id}/reject", response_model=ReportSummary)
async def reject_report(
    request: Request,
    report_id: int,
    body: RejectRequest,
    background_tasks: BackgroundTasks,
    reviewer: User = Depends(require_reviewer),
    client: Client = Depends(_get_client),
    session: AsyncSession = Depends(get_session),
) -> ReportSummary:
    """Reject and trigger redraft (or needs_manual_revision on 4th rejection)."""
    settings = request.app.state.settings
    async with session.begin():
        report = await svc.reject_report(
            report_id=report_id,
            client_id=client.id,
            reviewer=reviewer,
            comment=body.comment,
            redraft_cap=settings.report_redraft_cap,
            session=session,
            dispatcher=request.app.state.dispatcher,
        )

    # Trigger redraft after commit if not at cap
    if ReportStatus(report.status) == ReportStatus.DRAFTED:
        from app.reports.runner import redraft_report

        background_tasks.add_task(
            redraft_report,
            report_id=report_id,
            comment=body.comment,
            app_state=request.app.state,
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
    async with session.begin():
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
    async with session.begin():
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
    async with session.begin():
        await svc.discard_finding_permanently(
            report_id=report_id,
            finding_id=finding_id,
            client_id=client.id,
            reviewer=reviewer,
            session=session,
            dispatcher=request.app.state.dispatcher,
        )


# ── Batch consolidation ───────────────────────────────────────────────────────


@router.post("/watchlists/{watchlist_id}/consolidate-batch")
async def consolidate_batch_route(
    request: Request,
    watchlist_id: int,
    cycle_start: datetime = Query(..., description="Cycle period start (ISO-8601)"),
    cycle_end: datetime = Query(..., description="Cycle period end (ISO-8601)"),
    staff: User = Depends(require_staff),
    client: Client = Depends(_get_client),
    session: AsyncSession = Depends(get_session),
) -> ConsolidateResponse | None:
    """Consolidate pending_batch findings for a watchlist cycle into one batch report."""
    # Capture all primitives inside the transaction (avoid post-commit attribute expiry).
    async with session.begin():
        report = await consolidate_batch(
            watchlist_id=watchlist_id,
            client_id=client.id,
            cycle_period_start=cycle_start,
            cycle_period_end=cycle_end,
            session=session,
            dispatcher=request.app.state.dispatcher,
        )
        if report is None:
            result = None
        else:
            included = (
                (
                    await session.execute(
                        select(ReportFinding).where(ReportFinding.report_id == report.id)
                    )
                )
                .scalars()
                .all()
            )
            result = ConsolidateResponse(
                report_id=report.id,
                status=ReportStatus(report.status),
                finding_count=len(included),
            )

    if result is None:
        from fastapi.responses import Response

        return Response(status_code=status.HTTP_204_NO_CONTENT)  # type: ignore[return-value]
    return result


# ── Admin re-trigger for expedited draft ─────────────────────────────────────


@router.post("/findings/{finding_id}/draft", response_model=ReportSummary)
async def retrigger_expedited_draft(
    request: Request,
    finding_id: int,
    background_tasks: BackgroundTasks,
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

    # Check for existing active expedited report
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

    # Schedule a fresh draft
    from app.reports.runner import draft_expedited

    background_tasks.add_task(draft_expedited, finding_id, request.app.state)
    raise HTTPException(status.HTTP_202_ACCEPTED, detail="draft_scheduled")
