"""Triage backstop sweep (SC-001): re-triage documents that were never triaged and re-enqueue
orphaned expedited findings.

This is the safety net behind the inline fail-safe (Constitution III). Steps 1–4 of the
fail-safe cluster already escalate per-drug classifier failures and mark a document degraded on a
NER/other failure, so true *partial* suppression no longer occurs (a persist failure rolls the
whole document back; a classifier outage escalates each drug). What remains for the sweep is the
case where triage never ran at all (e.g. the worker crashed before the after-index hook) and the
2B orphan: a finding stuck PENDING_EXPEDITED whose draft was never enqueued. The sweep *remediates*
(re-enqueues) rather than only logging, and is noise-free: a legitimately-zero-finding document has
triaged_at set and is never flagged.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.embedding.enums import DocumentIndexStatus
from app.embedding.models import DocumentIndexState
from app.triage.enums import FindingStatus
from app.triage.models import Finding

_log = structlog.get_logger(__name__)


def _staleness_cutoff() -> datetime:
    """Documents/findings older than this without progress are considered stuck."""
    minutes = get_settings().triage_staleness_max_age_minutes
    return datetime.now(tz=UTC) - timedelta(minutes=minutes)


async def find_untriaged_documents(session: AsyncSession) -> list[tuple[int, int]]:
    """Return (document_id, client_id) for INDEXED documents never successfully triaged.

    triaged_at IS NULL means triage never completed (it was never run, or it failed); the staleness
    window excludes documents whose triage is merely in flight. This is the noise-free successor to
    the old zero-finding heuristic — a legitimately-zero-finding document has triaged_at set.
    """
    from sqlalchemy import select

    stmt = select(DocumentIndexState.document_id, DocumentIndexState.client_id).where(
        DocumentIndexState.status == DocumentIndexStatus.INDEXED,
        DocumentIndexState.triaged_at.is_(None),
        DocumentIndexState.updated_at < _staleness_cutoff(),
    )
    return [(row[0], row[1]) for row in (await session.execute(stmt)).all()]


async def find_orphaned_expedited(session: AsyncSession) -> list[tuple[int, int]]:
    """Return (finding_id, client_id) stuck PENDING_EXPEDITED past the staleness window.

    create_expedited_report flips a finding PENDING_EXPEDITED → PROCESSING, so a finding still
    PENDING_EXPEDITED after the window never got its draft (the 2B orphan). The window excludes
    findings whose draft job is merely in flight.
    """
    from sqlalchemy import select

    stmt = select(Finding.id, Finding.client_id).where(
        Finding.status == FindingStatus.PENDING_EXPEDITED,
        Finding.updated_at < _staleness_cutoff(),
    )
    return [(row[0], row[1]) for row in (await session.execute(stmt)).all()]


async def run_triage_sweep(wc: Any) -> dict[str, int]:
    """One sweep pass: re-triage untriaged documents + re-enqueue orphaned expedited findings.

    Returns {"retriaged": n, "reexpedited": m}. Re-enqueue uses deterministic job_ids
    (retriage:{doc} / expedited:{finding}:0), so a sweep that overlaps an in-flight or completed
    job is an idempotent no-op. Each flagged item also emits an operator alert for visibility.
    """
    from app.jobs.enqueue import enqueue

    result = {"retriaged": 0, "reexpedited": 0}

    async with wc.session_factory() as session:
        untriaged = await find_untriaged_documents(session)
        orphaned = await find_orphaned_expedited(session)

    for document_id, client_id in untriaged:
        _log.warning(
            "triage.operator_alert",
            stage="sweep",
            document_id=document_id,
            client_id=client_id,
            reason="indexed_but_never_triaged",
        )
        await enqueue(
            "task_retriage_document",
            job_id=f"retriage:{document_id}",
            app_state=wc,
            document_id=document_id,
            client_id=client_id,
        )
        result["retriaged"] += 1

    for finding_id, client_id in orphaned:
        _log.warning(
            "triage.operator_alert",
            stage="sweep",
            finding_id=finding_id,
            client_id=client_id,
            reason="expedited_without_draft",
        )
        await enqueue(
            "task_expedited",
            job_id=f"expedited:{finding_id}:0",
            app_state=wc,
            finding_id=finding_id,
            revision=0,
        )
        result["reexpedited"] += 1

    if untriaged or orphaned:
        _log.info("triage.sweep.done", **result)
        # The backstop firing means something upstream silently failed to triage — page it (A2).
        from app.observability.sentry import capture_operator_alert

        capture_operator_alert(
            "triage.sweep.remediated",
            retriaged=result["retriaged"],
            reexpedited=result["reexpedited"],
        )
    return result
