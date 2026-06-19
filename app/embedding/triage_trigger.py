"""After-index hook: run triage on a freshly-indexed document, then schedule expedited drafting."""

from collections.abc import Callable
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.modelserver_client import ModelserverClient

_log = structlog.get_logger(__name__)


def _failure_code(exc: Exception) -> str:
    """Short, PII-free reason code for the degraded marker (the full message goes only to logs)."""
    from app.triage.ner import NerUnavailable

    if isinstance(exc, NerUnavailable):
        return "ner_unavailable"
    return type(exc).__name__[:255]


async def _mark_triage_degraded(
    session_factory: Callable[[], AsyncSession],
    document: Any,
    client_id: int,
    exc: Exception,
) -> None:
    """Record triage_failed_at on the document's index state — the durable degraded marker.

    Best-effort: a failure to record the marker must not crash the index loop (the document is
    already indexed). It is logged, and the staleness sweep remains the backstop (Constitution III).
    """
    from datetime import UTC, datetime

    from app.embedding.service import IndexBuildService

    try:
        async with session_factory() as session:
            async with session.begin():
                state = await IndexBuildService.get_or_create_index_state(
                    session, document.id, client_id
                )
                state.triage_failed_at = datetime.now(UTC)
                state.triage_error = _failure_code(exc)
    except Exception:
        _log.error(
            "triage.degraded_mark_failed",
            document_id=document.id,
            client_id=client_id,
            exc_info=True,
        )


async def _enqueue_expedited_drafts(outcomes: list, *, app_state: Any, client_id: int) -> None:
    """Enqueue a durable expedited draft for each urgent/emergency finding (spec 11 site 5).

    Each enqueue is guarded independently: a failure for one finding is surfaced as an operator
    alert — an unenqueued PENDING_EXPEDITED finding is the orphan we must avoid (no report → no
    SLA escalation) — and does NOT skip the remaining findings. The staleness sweep re-enqueues
    any PENDING_EXPEDITED finding that still has no report (the 2B backstop; idempotent job_id).
    """
    from app.jobs.enqueue import enqueue
    from app.triage.enums import Bucket

    for outcome in outcomes:
        if not (
            outcome.created
            and outcome.finding_id is not None
            and outcome.bucket in (Bucket.URGENT, Bucket.EMERGENCY)
        ):
            continue
        try:
            # G4: auto fan-out first draft revision = 0. Works from both API (app.state.arq) and
            # worker (WorkerContext.arq) — G5.
            await enqueue(
                "task_expedited",
                job_id=f"expedited:{outcome.finding_id}:0",
                app_state=app_state,
                finding_id=outcome.finding_id,
                revision=0,
            )
        except Exception as exc:
            _log.error(
                "triage.operator_alert",
                stage="expedited_enqueue",
                finding_id=outcome.finding_id,
                reason=str(exc),
                client_id=client_id,
            )


async def trigger_triage(
    *,
    session_factory: Callable[[], AsyncSession],
    document: Any,
    chunk_texts: list[str],
    client_id: int,
    modelserver_client: ModelserverClient,
    dispatcher: Any,
    app_state: Any = None,
) -> None:
    """Call triage then schedule expedited drafting for urgent/emergency findings (FR-009)."""
    try:
        from app.clients.models import Client, WatchlistItem
        from app.triage.runner import triage_document_runner

        document_text = " ".join(chunk_texts)

        # Load watchlist drug items for this document's provenance watchlists.
        watchlist_ids = [dw.watchlist_id for dw in (document.provenance or [])]
        watchlist_drugs: list[str] = []
        custom_keywords: list[dict] = []

        if watchlist_ids:
            async with session_factory() as session:
                items_result = await session.execute(
                    select(WatchlistItem).where(
                        WatchlistItem.watchlist_id.in_(watchlist_ids),
                        WatchlistItem.item_type == "drug",
                    )
                )
                watchlist_drugs = [i.value for i in items_result.scalars().all()]

                client_result = await session.execute(select(Client).where(Client.id == client_id))
                client_obj = client_result.scalar_one_or_none()
                if client_obj is not None:
                    custom_keywords = client_obj.custom_severity_keywords or []

        if not watchlist_drugs:
            _log.info(
                "triage.skip.no_watchlist_drugs",
                document_id=document.id,
                client_id=client_id,
            )
            return

        outcomes = await triage_document_runner(
            session_factory=session_factory,
            document_id=document.id,
            client_id=client_id,
            document_text=document_text,
            source_reliability=document.source_reliability,
            watchlist_drugs=watchlist_drugs,
            custom_keywords=custom_keywords,
            ms_client=modelserver_client,
            dispatcher=dispatcher,
        )
    except Exception as exc:
        _log.error(
            "triage.after_index.failed",
            document_id=document.id,
            client_id=client_id,
            error=str(exc),
            exc_info=True,
        )
        # Fail SAFE (Constitution III): record a durable degraded marker so the cycle cannot be
        # reported 'completed' clean. Best-effort — never raise out of the after-index hook (the
        # document is already indexed; the staleness sweep is the backstop if this write fails).
        await _mark_triage_degraded(session_factory, document, client_id, exc)
        return

    # Enqueue durable expedited drafting OUTSIDE the triage try/except: a PENDING_EXPEDITED finding
    # with no draft is the orphan to avoid (no report → no SLA), so an enqueue failure must surface
    # loudly and must not skip the other findings. By here every finding is committed — a persist
    # failure rolls back triage_document_runner and is handled by the degraded path above.
    if app_state is not None:
        await _enqueue_expedited_drafts(outcomes, app_state=app_state, client_id=client_id)
