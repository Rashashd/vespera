"""Report persistence, HITL state-machine transitions, and operator-alert handling."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.core.config import Settings
from app.domain.events import (
    FindingDiscarded,
    ReportApproved,
    ReportDiscarded,
    ReportDrafted,
    ReportEdited,
    ReportOperatorAlert,
    ReportRejected,
)
from app.reports.enums import FindingReportState, ReportStatus, ReportType
from app.reports.models import Report, ReportFinding, ReportFollowup
from app.triage.enums import FindingStatus
from app.triage.models import Finding

_log = structlog.get_logger(__name__)

# Allowed source statuses for reviewer actions (before terminal)
_REVIEW_STATUSES = {ReportStatus.DRAFTED, ReportStatus.UNDER_REVIEW}


def _now() -> datetime:
    return datetime.now(UTC)


async def _load_report_for_client(report_id: int, client_id: int, session: AsyncSession) -> Report:
    report = await session.get(Report, report_id)
    if report is None or report.client_id != client_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="REPORT_NOT_FOUND")
    return report


async def _load_report_finding(
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


# ── Expedited draft creation ─────────────────────────────────────────────────


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

    claims = draft_outcome.get("claims", [])
    draft_body = draft_outcome.get("draft_body", "")
    corroboration_count = draft_outcome.get("corroboration_count", 0)
    corroboration_sources = draft_outcome.get("corroboration_sources", [])

    sla_deadline = _now() + timedelta(hours=settings.expedited_sla_hours)

    report = Report(
        client_id=finding.client_id,
        report_type=ReportType.EXPEDITED,
        status=ReportStatus.DRAFTED,
        structured_fields=claims,
        draft_body=draft_body,
        corroboration_count=corroboration_count,
        corroboration_sources=corroboration_sources,
        revision_count=0,
        reviewer_comments=[],
        sla_deadline=sla_deadline,
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(report)
    await session.flush()

    rf = ReportFinding(
        report_id=report.id,
        finding_id=finding.id,
        client_id=finding.client_id,
        report_type=ReportType.EXPEDITED,
        state=FindingReportState.INCLUDED,
        created_at=_now(),
    )
    session.add(rf)

    # Claim finding: pending_expedited → processing
    finding.status = FindingStatus.PROCESSING
    finding.updated_at = _now()

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
    # Idempotency: one per finding
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
        created_at=_now(),
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


# ── HITL state-machine transitions ───────────────────────────────────────────


async def approve_report(
    *,
    report_id: int,
    client_id: int,
    reviewer: User,
    session: AsyncSession,
    dispatcher: Any,
) -> Report:
    """Approve a report: drafted|under_review → approved."""
    report = await _load_report_for_client(report_id, client_id, session)
    if ReportStatus(report.status) not in _REVIEW_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="invalid_status_transition")

    report.status = ReportStatus.APPROVED
    report.updated_at = _now()
    report.reviewer_comments = list(report.reviewer_comments or []) + [
        {"reviewer_id": reviewer.id, "action": "approve", "ts": _now().isoformat()}
    ]
    # Mark linked expedited finding as reported
    await _mark_expedited_finding_reported(report, session)

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
    report = await _load_report_for_client(report_id, client_id, session)
    if ReportStatus(report.status) not in _REVIEW_STATUSES:
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
    report.updated_at = _now()
    report.reviewer_comments = list(report.reviewer_comments or []) + [
        {
            "reviewer_id": reviewer.id,
            "action": "edit_approve",
            "comment": comment,
            "ts": _now().isoformat(),
        }
    ]
    await _mark_expedited_finding_reported(report, session)

    await dispatcher.dispatch(
        ReportEdited(
            actor_id=reviewer.id,
            actor_type="human",
            client_id=client_id,
            report_id=report_id,
            report_type=report.report_type,
        ),
        session,
    )
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
    report = await _load_report_for_client(report_id, client_id, session)
    if ReportStatus(report.status) not in _REVIEW_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="invalid_status_transition")

    new_revision_count = (report.revision_count or 0) + 1
    report.revision_count = new_revision_count
    report.reviewer_comments = list(report.reviewer_comments or []) + [
        {
            "reviewer_id": reviewer.id,
            "action": "reject",
            "comment": comment,
            "ts": _now().isoformat(),
        }
    ]
    # Allow `redraft_cap` redraft rounds; escalate on the (cap+1)th rejection (FR-016/SC-005).
    if new_revision_count > redraft_cap:
        report.status = ReportStatus.NEEDS_MANUAL_REVISION
    else:
        report.status = ReportStatus.DRAFTED  # redraft run will refresh the body
    report.updated_at = _now()

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
    report = await _load_report_for_client(report_id, client_id, session)
    if ReportStatus(report.status).is_terminal:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="already_terminal")

    report.status = ReportStatus.DISCARDED
    report.updated_at = _now()
    report.reviewer_comments = list(report.reviewer_comments or []) + [
        {"reviewer_id": reviewer.id, "action": "discard", "ts": _now().isoformat()}
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
                finding.updated_at = _now()

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
    rf = await _load_report_finding(report_id, finding_id, client_id, session)
    rf.state = FindingReportState.DROPPED
    finding = await session.get(Finding, finding_id)
    if finding:
        finding.status = FindingStatus.PENDING_BATCH
        finding.updated_at = _now()

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
    await _maybe_auto_discard_batch(report_id, client_id, reviewer, session, dispatcher)


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
    rf = await _load_report_finding(report_id, finding_id, client_id, session)
    rf.state = FindingReportState.DISCARDED
    finding = await session.get(Finding, finding_id)
    if finding:
        finding.status = FindingStatus.DISCARDED
        finding.updated_at = _now()

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
    await _maybe_auto_discard_batch(report_id, client_id, reviewer, session, dispatcher)


# ── Internal helpers ─────────────────────────────────────────────────────────


async def _mark_expedited_finding_reported(report: Report, session: AsyncSession) -> None:
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
            finding.updated_at = _now()


async def _maybe_auto_discard_batch(
    report_id: int,
    client_id: int,
    reviewer: User,
    session: AsyncSession,
    dispatcher: Any,
) -> None:
    """Auto-discard the batch report if no included findings remain (FR-013a)."""
    included_count = (
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
    if included_count:
        return
    report = await session.get(Report, report_id)
    if report and not ReportStatus(report.status).is_terminal:
        report.status = ReportStatus.DISCARDED
        report.updated_at = _now()
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
