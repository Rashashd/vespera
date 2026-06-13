"""Reviewer HITL state-machine transitions on reports and their findings."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.domain.events import (
    FindingDiscarded,
    ReportApproved,
    ReportDiscarded,
    ReportEdited,
    ReportRejected,
)
from app.reports._helpers import (
    REVIEW_STATUSES,
    load_report_finding,
    load_report_for_client,
    mark_expedited_finding_reported,
    maybe_auto_discard_batch,
    now_utc,
)
from app.reports.enums import FindingReportState, ReportStatus, ReportType
from app.reports.models import Report, ReportFinding
from app.triage.enums import FindingStatus
from app.triage.models import Finding


async def approve_report(
    *,
    report_id: int,
    client_id: int,
    reviewer: User,
    session: AsyncSession,
    dispatcher: Any,
) -> Report:
    """Approve a report: drafted|under_review → approved."""
    report = await load_report_for_client(report_id, client_id, session)
    if ReportStatus(report.status) not in REVIEW_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="invalid_status_transition")

    report.status = ReportStatus.APPROVED
    report.updated_at = now_utc()
    report.reviewer_comments = list(report.reviewer_comments or []) + [
        {"reviewer_id": reviewer.id, "action": "approve", "ts": now_utc().isoformat()}
    ]
    await mark_expedited_finding_reported(report, session)

    await dispatcher.dispatch(
        ReportApproved(
            actor_id=reviewer.id,
            actor_type="human",
            client_id=client_id,
            report_id=report_id,
            report_type=report.report_type,
        ),
        session,
    )
    return report


async def edit_approve_report(
    *,
    report_id: int,
    client_id: int,
    reviewer: User,
    draft_body: str,
    structured_fields: list[dict],
    comment: str,
    session: AsyncSession,
    dispatcher: Any,
) -> Report:
    """Edit content then approve; edited claims tagged reviewer_attested."""
    report = await load_report_for_client(report_id, client_id, session)
    if ReportStatus(report.status) not in REVIEW_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="invalid_status_transition")

    # Preserve provenance for claims left unchanged; tag only edited/new claims as
    # reviewer_attested (FR-017/D5). Match against original claims by (field, text).
    original_grounded = {
        (c.get("field"), c.get("text")): c
        for c in (report.structured_fields or [])
        if c.get("provenance") == "drafted_grounded"
    }
    submitted = structured_fields if structured_fields else list(report.structured_fields or [])
    merged_fields = []
    for c in submitted:
        match = original_grounded.get((c.get("field"), c.get("text")))
        if match is not None:
            merged_fields.append(match)  # unchanged → keep drafted_grounded + source_ref
        else:
            merged_fields.append({**c, "provenance": "reviewer_attested"})
    report.structured_fields = merged_fields
    report.draft_body = draft_body or report.draft_body
    report.status = ReportStatus.APPROVED
    report.updated_at = now_utc()
    report.reviewer_comments = list(report.reviewer_comments or []) + [
        {
            "reviewer_id": reviewer.id,
            "action": "edit_approve",
            "comment": comment,
            "ts": now_utc().isoformat(),
        }
    ]
    await mark_expedited_finding_reported(report, session)

    for event in (ReportEdited, ReportApproved):
        await dispatcher.dispatch(
            event(
                actor_id=reviewer.id,
                actor_type="human",
                client_id=client_id,
                report_id=report_id,
                report_type=report.report_type,
            ),
            session,
        )
    return report


async def reject_report(
    *,
    report_id: int,
    client_id: int,
    reviewer: User,
    comment: str,
    redraft_cap: int,
    session: AsyncSession,
    dispatcher: Any,
) -> Report:
    """Reject: triggers redraft (rev_count++) or needs_manual_revision on 4th rejection."""
    report = await load_report_for_client(report_id, client_id, session)
    if ReportStatus(report.status) not in REVIEW_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="invalid_status_transition")

    new_revision_count = (report.revision_count or 0) + 1
    report.revision_count = new_revision_count
    report.reviewer_comments = list(report.reviewer_comments or []) + [
        {
            "reviewer_id": reviewer.id,
            "action": "reject",
            "comment": comment,
            "ts": now_utc().isoformat(),
        }
    ]
    # Allow `redraft_cap` redraft rounds; escalate on the (cap+1)th rejection (FR-016/SC-005).
    if new_revision_count > redraft_cap:
        report.status = ReportStatus.NEEDS_MANUAL_REVISION
    else:
        report.status = ReportStatus.DRAFTED  # redraft run will refresh the body
    report.updated_at = now_utc()

    await dispatcher.dispatch(
        ReportRejected(
            actor_id=reviewer.id,
            actor_type="human",
            client_id=client_id,
            report_id=report_id,
            report_type=report.report_type,
            revision_count=new_revision_count,
        ),
        session,
    )
    return report


async def discard_report(
    *,
    report_id: int,
    client_id: int,
    reviewer: User,
    session: AsyncSession,
    dispatcher: Any,
) -> Report:
    """Discard a report (terminal). For expedited: mark linked report_finding discarded."""
    report = await load_report_for_client(report_id, client_id, session)
    if ReportStatus(report.status).is_terminal:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="already_terminal")

    report.status = ReportStatus.DISCARDED
    report.updated_at = now_utc()
    report.reviewer_comments = list(report.reviewer_comments or []) + [
        {"reviewer_id": reviewer.id, "action": "discard", "ts": now_utc().isoformat()}
    ]

    # Mark all report_findings as discarded so the expedited partial unique is released
    rf_rows = (
        (await session.execute(select(ReportFinding).where(ReportFinding.report_id == report_id)))
        .scalars()
        .all()
    )
    for rf in rf_rows:
        rf.state = FindingReportState.DISCARDED
        # Return pending_expedited findings to pending_expedited (not terminal)
        if rf.report_type == ReportType.EXPEDITED:
            finding = await session.get(Finding, rf.finding_id)
            if finding and finding.status == "processing":
                finding.status = FindingStatus.PENDING_EXPEDITED
                finding.updated_at = now_utc()

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
    return report


async def drop_finding_from_report(
    *,
    report_id: int,
    finding_id: int,
    client_id: int,
    reviewer: User,
    session: AsyncSession,
    dispatcher: Any,
) -> None:
    """Drop a finding from a batch report (back to pending_batch); auto-discard if empty."""
    rf = await load_report_finding(report_id, finding_id, client_id, session)
    rf.state = FindingReportState.DROPPED
    finding = await session.get(Finding, finding_id)
    if finding:
        finding.status = FindingStatus.PENDING_BATCH
        finding.updated_at = now_utc()

    await dispatcher.dispatch(
        FindingDiscarded(
            actor_id=reviewer.id,
            actor_type="human",
            client_id=client_id,
            finding_id=finding_id,
            kind="drop",
        ),
        session,
    )
    await maybe_auto_discard_batch(report_id, client_id, reviewer, session, dispatcher)


async def discard_finding_permanently(
    *,
    report_id: int,
    finding_id: int,
    client_id: int,
    reviewer: User,
    session: AsyncSession,
    dispatcher: Any,
) -> None:
    """Permanently discard a finding from a batch report (terminal for the finding)."""
    rf = await load_report_finding(report_id, finding_id, client_id, session)
    rf.state = FindingReportState.DISCARDED
    finding = await session.get(Finding, finding_id)
    if finding:
        finding.status = FindingStatus.DISCARDED
        finding.updated_at = now_utc()

    await dispatcher.dispatch(
        FindingDiscarded(
            actor_id=reviewer.id,
            actor_type="human",
            client_id=client_id,
            finding_id=finding_id,
            kind="permanent",
        ),
        session,
    )
    await maybe_auto_discard_batch(report_id, client_id, reviewer, session, dispatcher)
