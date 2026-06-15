"""ARQ task wrappers: deterministic job_ids, retry/dead-letter, chain advancement (spec 11)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

from app.jobs.context import WorkerContext
from app.jobs.dead_letter import record as dl_record
from app.jobs.enqueue import enqueue, register_task
from app.jobs.retry import PermanentJobError, is_permanent

_log = structlog.get_logger(__name__)


async def _run_with_dlq(
    ctx: dict,
    *,
    fn: Any,
    job_name: str,
    job_key: str,
    client_id: int | None,
    fn_kwargs: dict,
    cycle_id: int | None = None,
    failure_stage: str | None = None,
) -> Any:
    """Execute fn; on final retry or PermanentJobError, record dead-letter and re-raise.

    When cycle_id is set, a final failure (transient exhaustion OR PermanentJobError) also
    marks the cycle ``failed`` with ``failure_stage`` (FR-018). That excludes the watchlist
    from auto-scheduling until an operator abandons the cycle (FR-018a/b) — without it the
    cycle would stay ``in_progress`` forever and the watchlist would never reschedule.
    """
    wc = WorkerContext(ctx)
    job_try: int = ctx.get("job_try", 1)
    max_tries: int = ctx.get("max_tries", 3)
    first_failed_at: datetime = ctx.get("first_failed_at", datetime.now(UTC))

    try:
        return await fn(**fn_kwargs)
    except Exception as exc:
        is_final = is_permanent(exc) or job_try >= max_tries
        if is_final:
            await dl_record(
                job_name=job_name,
                job_key=job_key,
                client_id=client_id,
                args={k: v for k, v in fn_kwargs.items() if not callable(v)},
                exc=exc,
                attempts=job_try,
                first_failed_at=first_failed_at,
                session_factory=wc.session_factory,
                dispatcher=wc.dispatcher,
            )
            if cycle_id is not None:
                from app.scheduling.service import CycleService

                async with wc.session_factory() as session:
                    async with session.begin():
                        await CycleService.mark_failed(session, cycle_id, failure_stage or job_name)
        if is_permanent(exc):
            # Swallow so ARQ does not retry; already dead-lettered above
            _log.error(
                "job.permanent_failure",
                job_name=job_name,
                job_key=job_key,
                error_class=type(exc).__name__,
            )
            return None
        raise  # transient — let ARQ retry


# ── task_run_ingestion ────────────────────────────────────────────────────────


async def task_run_ingestion(
    ctx: dict,
    *,
    run_id: int,
    client_id: int,
    watchlist_id: int,
    cycle_id: int | None = None,
) -> None:
    """Durable ingestion stage; on success enqueues task_index_build for cycle path."""
    from app.clients.watchlists import get_watchlist
    from app.ingestion.runner import run_ingestion

    wc = WorkerContext(ctx)
    job_key = f"ingest:{run_id}"

    async def _run() -> None:
        # Re-query watchlist + items in worker session (implementation-notes §3)
        async with wc.session_factory() as session:
            watchlist = await get_watchlist(session, client_id, watchlist_id)
            if watchlist is None:
                raise PermanentJobError(f"watchlist {watchlist_id} not found or wrong client")
            items_snapshot = list(watchlist.items)

        settings = wc.settings
        await run_ingestion(
            run_id=run_id,
            client_id=client_id,
            watchlist_id=watchlist_id,
            watchlist_items=items_snapshot,
            session_factory=wc.session_factory,
            initial_lookback_days=settings.ingestion_initial_lookback_days,
            per_source_cap=settings.ingestion_per_source_cap,
        )
        # Advance cycle to index stage if this is a scheduled cycle
        if cycle_id is not None:
            from app.scheduling.service import CycleService

            async with wc.session_factory() as session:
                async with session.begin():
                    await CycleService.advance_stage(session, cycle_id, "index")

            await enqueue(
                "task_index_build",
                job_id=f"index:{client_id}:{watchlist_id}:{cycle_id}",
                _ctx=ctx,
                client_id=client_id,
                watchlist_id=watchlist_id,
                cycle_id=cycle_id,
            )

    await _run_with_dlq(
        ctx,
        fn=_run,
        job_name="task_run_ingestion",
        job_key=job_key,
        client_id=client_id,
        fn_kwargs={},
        cycle_id=cycle_id,
        failure_stage="ingestion",
    )

    _log.info("task_run_ingestion.done", run_id=run_id, client_id=client_id, cycle_id=cycle_id)


# ── task_index_build ──────────────────────────────────────────────────────────


async def task_index_build(
    ctx: dict,
    *,
    client_id: int,
    watchlist_id: int | None = None,
    cycle_id: int | None = None,
) -> None:
    """Durable index+triage stage. Watchlist-scoped for cycles, client-wide for manual."""
    from app.embedding.runner import index_build_runner
    from app.infra.modelserver_client import ModelserverClient

    wc = WorkerContext(ctx)
    job_key = (
        f"index:{client_id}:{watchlist_id}:{cycle_id}"
        if cycle_id is not None
        else f"index:{client_id}:manual"
    )

    async def _run() -> None:
        async with ModelserverClient.from_settings(wc.settings) as ms_client:
            run = await index_build_runner(
                session_factory=wc.session_factory,
                client_id=client_id,
                watchlist_id=watchlist_id,
                modelserver_client=ms_client,
                dispatcher=wc.dispatcher,
                app_state=wc,
            )
        if cycle_id is None:
            return  # manual client-wide build — no cycle to advance

        # Cycle path: triage + expedited fan-out already fired inline during indexing
        # (no join — FR-015a). Link provenance, move to the consolidation stage, and enqueue
        # task_consolidate — the stage that actually completes the cycle (FR-001, contract).
        from app.scheduling.service import CycleService

        async with wc.session_factory() as session:
            async with session.begin():
                cycle = await CycleService.advance_stage(session, cycle_id, "consolidation")
                if cycle is None:
                    return
                if run is not None:
                    await CycleService.set_index_build_run(session, cycle_id, run.id)
                period_start_iso = cycle.period_start.isoformat()
                period_end_iso = cycle.period_end.isoformat()

        await enqueue(
            "task_consolidate",
            job_id=f"consolidate:{cycle_id}",
            _ctx=ctx,
            watchlist_id=watchlist_id,
            client_id=client_id,
            cycle_period_start=period_start_iso,
            cycle_period_end=period_end_iso,
            cycle_id=cycle_id,
        )

    await _run_with_dlq(
        ctx,
        fn=_run,
        job_name="task_index_build",
        job_key=job_key,
        client_id=client_id,
        fn_kwargs={},
        cycle_id=cycle_id,
        failure_stage="index",
    )

    _log.info(
        "task_index_build.done",
        client_id=client_id,
        watchlist_id=watchlist_id,
        cycle_id=cycle_id,
    )


# ── task_expedited ────────────────────────────────────────────────────────────


async def task_expedited(
    ctx: dict,
    *,
    finding_id: int,
    revision: int = 0,
) -> None:
    """Durable expedited-report draft; job_id = expedited:{finding_id}:{revision}."""
    from app.reports.runner import draft_expedited

    wc = WorkerContext(ctx)
    job_key = f"expedited:{finding_id}:{revision}"

    async def _run() -> None:
        await draft_expedited(finding_id, wc)

    await _run_with_dlq(
        ctx,
        fn=_run,
        job_name="task_expedited",
        job_key=job_key,
        client_id=None,  # finding carries client_id; not available here without a DB call
        fn_kwargs={},
    )

    _log.info("task_expedited.done", finding_id=finding_id, revision=revision)


# ── task_redraft ──────────────────────────────────────────────────────────────


async def task_redraft(
    ctx: dict,
    *,
    report_id: int,
    revision: int,
    comment: str,
) -> None:
    """Durable redraft after reviewer rejection; job_id = redraft:{report_id}:{revision}."""
    from app.reports.runner import redraft_report

    wc = WorkerContext(ctx)
    job_key = f"redraft:{report_id}:{revision}"

    async def _run() -> None:
        await redraft_report(report_id=report_id, comment=comment, app_state=wc)

    await _run_with_dlq(
        ctx,
        fn=_run,
        job_name="task_redraft",
        job_key=job_key,
        client_id=None,
        fn_kwargs={},
    )

    _log.info("task_redraft.done", report_id=report_id, revision=revision)


# ── task_consolidate ──────────────────────────────────────────────────────────


async def task_consolidate(
    ctx: dict,
    *,
    watchlist_id: int,
    client_id: int,
    cycle_period_start: str,  # ISO-8601 string (serializable)
    cycle_period_end: str,
    cycle_id: int | None = None,
) -> None:
    """Durable batch consolidation; honors budget gate on cycle path."""
    from app.reports.consolidation import consolidate_batch

    wc = WorkerContext(ctx)
    job_key = (
        f"consolidate:{cycle_id}"
        if cycle_id is not None
        else f"consolidate:manual:{watchlist_id}:{cycle_period_start}"
    )

    async def _run() -> None:
        period_start = datetime.fromisoformat(cycle_period_start)
        period_end = datetime.fromisoformat(cycle_period_end)

        # Budget gate (cycle path only; manual triggers bypass — FR-019)
        if cycle_id is not None:
            from app.scheduling.budget_policy import gate

            # MUST commit: gate() dispatches WatchlistBudgetThresholdReached, whose audit row
            # is staged on this session and would be rolled back without an explicit
            # transaction (FR-019c — budget threshold surfaced to audit/dashboard).
            async with wc.session_factory() as session:
                async with session.begin():
                    policy = await gate(session, watchlist_id, client_id, wc.dispatcher)

            if policy == "pause":
                _log.info(
                    "task_consolidate.budget_pause",
                    watchlist_id=watchlist_id,
                    cycle_id=cycle_id,
                )
                from app.scheduling.service import CycleService

                async with wc.session_factory() as session:
                    async with session.begin():
                        await CycleService.mark_completed(
                            session, cycle_id, skipped_reason="budget_pause"
                        )
                return

            if policy == "critical_only":
                _log.info(
                    "task_consolidate.budget_critical_only",
                    watchlist_id=watchlist_id,
                    cycle_id=cycle_id,
                )
                from app.scheduling.service import CycleService

                async with wc.session_factory() as session:
                    async with session.begin():
                        await CycleService.mark_completed(
                            session, cycle_id, skipped_reason="budget_critical_only"
                        )
                return

        async with wc.session_factory() as session:
            async with session.begin():
                await consolidate_batch(
                    watchlist_id=watchlist_id,
                    client_id=client_id,
                    cycle_period_start=period_start,
                    cycle_period_end=period_end,
                    session=session,
                    dispatcher=wc.dispatcher,
                )

        if cycle_id is not None:
            from app.scheduling.service import CycleService

            async with wc.session_factory() as session:
                async with session.begin():
                    await CycleService.mark_completed(session, cycle_id)

    await _run_with_dlq(
        ctx,
        fn=_run,
        job_name="task_consolidate",
        job_key=job_key,
        client_id=client_id,
        fn_kwargs={},
        cycle_id=cycle_id,
        failure_stage="consolidation",
    )

    _log.info(
        "task_consolidate.done",
        watchlist_id=watchlist_id,
        client_id=client_id,
        cycle_id=cycle_id,
    )


# ── task_cycle_start ──────────────────────────────────────────────────────────


async def task_cycle_start(
    ctx: dict,
    *,
    watchlist_id: int,
    client_id: int,
    period_start: str,  # ISO-8601
    period_end: str,
) -> None:
    """Start a new cycle and enqueue ingestion (scheduler → ingest → index → ... → consolidate)."""
    from app.scheduling.service import CycleService

    wc = WorkerContext(ctx)
    job_key = f"cycle-start:{watchlist_id}:{period_start}"

    async def _run() -> None:
        from app.ingestion.service import create_run

        # Idempotent re-entry (FR-005/SC-002): a retried task_cycle_start must reuse the
        # in_progress cycle it already created — re-running start_cycle would hit the
        # partial-unique guard, dead-letter, and strand the cycle in_progress forever.
        async with wc.session_factory() as session:
            async with session.begin():
                cycle = await CycleService.get_in_progress(session, watchlist_id)
                if cycle is None:
                    try:
                        cycle = await CycleService.start_cycle(
                            session,
                            watchlist_id=watchlist_id,
                            client_id=client_id,
                            period_start=datetime.fromisoformat(period_start),
                            period_end=datetime.fromisoformat(period_end),
                        )
                    except Exception as exc:
                        raise PermanentJobError(str(exc)) from exc
                cycle_id = cycle.id
                run_id = cycle.ingestion_run_id

        # Create the ingestion run only if this cycle doesn't already have one (retry-safe).
        if run_id is None:
            async with wc.session_factory() as session:
                async with session.begin():
                    run = await create_run(
                        session,
                        client_id=client_id,
                        watchlist_id=watchlist_id,
                        triggered_by_user_id=None,
                    )
                    run_id = run.id
                    await CycleService.set_ingestion_run(session, cycle_id, run_id)

        await enqueue(
            "task_run_ingestion",
            job_id=f"ingest:{run_id}",
            _ctx=ctx,
            run_id=run_id,
            client_id=client_id,
            watchlist_id=watchlist_id,
            cycle_id=cycle_id,
        )

    await _run_with_dlq(
        ctx,
        fn=_run,
        job_name="task_cycle_start",
        job_key=job_key,
        client_id=client_id,
        fn_kwargs={},
    )

    _log.info(
        "task_cycle_start.done",
        watchlist_id=watchlist_id,
        client_id=client_id,
        period_start=period_start,
    )


# ── Register all tasks for inline mode ───────────────────────────────────────
register_task("task_run_ingestion", task_run_ingestion)
register_task("task_index_build", task_index_build)
register_task("task_expedited", task_expedited)
register_task("task_redraft", task_redraft)
register_task("task_consolidate", task_consolidate)
register_task("task_cycle_start", task_cycle_start)
