"""Hourly cron: select due watchlists → enqueue task_cycle_start for each (spec 11 FR-013)."""

from __future__ import annotations

import structlog

from app.jobs.context import WorkerContext
from app.jobs.enqueue import enqueue
from app.scheduling.due import compute_period

_log = structlog.get_logger(__name__)


async def scheduler_tick(ctx: dict) -> None:
    """ARQ cron job: fires hourly; starts one cycle per due watchlist (FR-015b coalescing)."""
    from app.scheduling.service import CycleService

    wc = WorkerContext(ctx)

    async with wc.session_factory() as session:
        due_watchlists = await CycleService.query_due_watchlists(session)

    _log.info("scheduler_tick.due", count=len(due_watchlists))

    for entry in due_watchlists:
        watchlist_id = entry["watchlist_id"]
        client_id = entry["client_id"]
        cadence = entry["cadence"]
        last_completed_at = entry["last_completed_at"]

        period_start, period_end = compute_period(
            cadence=cadence, last_completed_at=last_completed_at
        )
        period_start_iso = period_start.isoformat()

        await enqueue(
            "task_cycle_start",
            job_id=f"cycle-start:{watchlist_id}:{period_start_iso}",
            _ctx=ctx,
            watchlist_id=watchlist_id,
            client_id=client_id,
            period_start=period_start_iso,
            period_end=period_end.isoformat(),
        )
        _log.info(
            "scheduler_tick.cycle_enqueued",
            watchlist_id=watchlist_id,
            client_id=client_id,
            period_start=period_start_iso,
        )
