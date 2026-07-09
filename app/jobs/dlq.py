"""Durable job-execution harness: retry, dead-letter capture, and cycle-failure marking.

Shared by every ARQ task in ``app/jobs/tasks.py`` (spec 11). Extracted from the task
catalog so the execution/retry policy lives in one place, separate from the task
definitions themselves.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

from app.jobs.context import WorkerContext
from app.jobs.dead_letter import record as dl_record
from app.jobs.retry import is_permanent

_log = structlog.get_logger(__name__)


async def run_with_dlq(
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
