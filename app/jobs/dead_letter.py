"""Dead-letter recording and retention purge (spec 11 FR-009/FR-009a/FR-011)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from app.domain.events import JobDeadLettered

_log = structlog.get_logger(__name__)

_SYSTEM_ACTOR_ID = 0
_SYSTEM_ACTOR_TYPE = "system"


def _digest(args: dict[str, Any]) -> str:
    """SHA-256 of the non-PII arg identifiers only (ids/keys, never payloads — FR-011)."""
    safe = {
        k: v
        for k, v in args.items()
        if k.endswith("_id") or k in ("job_key", "job_name", "cycle_id", "run_id")
    }
    return hashlib.sha256(json.dumps(safe, sort_keys=True).encode()).hexdigest()


async def record(
    *,
    job_name: str,
    job_key: str,
    client_id: int | None,
    args: dict[str, Any],
    exc: BaseException,
    attempts: int,
    first_failed_at: datetime,
    session_factory: Any,
    dispatcher: Any,
) -> None:
    """Insert a dead_letter row and dispatch JobDeadLettered (system actor → audit).

    Deliberately avoids storing exception messages that may carry PII (FR-011).
    error_summary is kept to ≤200 chars and is never the full traceback.
    """
    from app.jobs.retry import PermanentJobError
    from app.scheduling.models import DeadLetter

    error_class = type(exc).__name__
    # FR-011: never persist arbitrary exception text — it may embed clinical/PII payload from
    # the failing job. Only PermanentJobError messages are author-controlled (validation /
    # business-rule strings) and safe to store; everything else keeps class-only. The full
    # error (with exc_info) still reaches the structured worker logs for debugging.
    error_summary = str(exc)[:200] if isinstance(exc, PermanentJobError) else None

    dl = DeadLetter(
        job_name=job_name,
        job_key=job_key,
        client_id=client_id,
        args_digest=_digest(args),
        error_class=error_class,
        error_summary=error_summary,
        attempts=attempts,
        first_failed_at=first_failed_at,
    )

    async with session_factory() as session:
        async with session.begin():
            session.add(dl)
            await session.flush()
            await dispatcher.dispatch(
                JobDeadLettered(
                    actor_id=_SYSTEM_ACTOR_ID,
                    actor_type=_SYSTEM_ACTOR_TYPE,
                    client_id=client_id,
                    job_name=job_name,
                    job_key=job_key,
                    attempts=attempts,
                    error_class=error_class,
                ),
                session,
            )

    _log.warning(
        "job.dead_lettered",
        job_name=job_name,
        job_key=job_key,
        client_id=client_id,
        error_class=error_class,
        attempts=attempts,
    )


async def purge_expired(ctx: dict) -> None:
    """ARQ cron: delete dead_letter rows older than dead_letter_retention_days (FR-009a).

    MUST NOT delete audit_log rows — they are in a separate table and never touched here.
    """
    from sqlalchemy import delete

    from app.jobs.context import WorkerContext
    from app.scheduling.models import DeadLetter

    wc = WorkerContext(ctx)
    cutoff = datetime.now(UTC) - timedelta(days=wc.settings.dead_letter_retention_days)

    async with wc.session_factory() as session:
        async with session.begin():
            result = await session.execute(
                delete(DeadLetter).where(DeadLetter.dead_lettered_at < cutoff)
            )
            count = result.rowcount

    _log.info("dead_letter.purge", cutoff=cutoff.isoformat(), deleted=count)
