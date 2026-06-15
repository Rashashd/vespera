"""Single entry point for all durable job enqueues (spec 11 FR-002a/FR-003/G5)."""

from __future__ import annotations

import inspect
from typing import Any

import structlog

_log = structlog.get_logger(__name__)

# Registry: job_name → coroutine function (populated by tasks.py on import)
_TASK_REGISTRY: dict[str, Any] = {}


def register_task(name: str, fn: Any) -> None:
    """Register a task coroutine so inline mode can look it up by name."""
    _TASK_REGISTRY[name] = fn


async def enqueue(
    name: str,
    *,
    job_id: str,
    app_state: Any = None,
    _ctx: dict | None = None,
    **kwargs: Any,
) -> None:
    """Enqueue a job by name.

    In production (jobs_inline=False): calls ArqRedis.enqueue_job with a deterministic
    job_id for idempotency. A duplicate job_id already queued/running returns None (no-op).

    In dev/test (jobs_inline=True): awaits the task coroutine in-process for exact parity
    (inline mode is NEVER active in production — SC-008).

    Args:
        name: ARQ function name (e.g. "task_run_ingestion").
        job_id: Deterministic logical key (D3); duplicate enqueues are no-ops.
        app_state: FastAPI app.state (API side). Exactly one of app_state or _ctx must be set.
        _ctx: ARQ worker ctx dict (worker side — G5: enqueue from within a running job).
        **kwargs: Arguments forwarded to the task function.

    Raises:
        RuntimeError: If jobs_inline=False and no ARQ connection is available (FR-002a).
    """
    from app.core.config import get_settings

    settings = get_settings()

    if settings.jobs_inline:
        fn = _TASK_REGISTRY.get(name)
        if fn is None:
            raise RuntimeError(f"jobs_inline: task {name!r} is not registered")
        # Build a minimal ctx-like object for inline execution
        ctx = _ctx or {}
        if app_state is not None:
            ctx = {
                "settings": app_state.settings,
                "session_factory": app_state.session_factory,
                "redis": getattr(app_state, "arq", getattr(app_state, "redis", None)),
                "dispatcher": app_state.dispatcher,
                "llm": getattr(app_state, "llm", None),
                "job_id": job_id,
                "job_try": 1,
            }
        sig = inspect.signature(fn)
        first_param = next(iter(sig.parameters))
        # Tasks take (ctx, ...) — pass ctx as the first positional arg
        if first_param in ("ctx",):
            await fn(ctx, **kwargs)
        else:
            await fn(**kwargs)
        return

    # --- Durable path: ARQ enqueue ---
    arq = None
    if _ctx is not None:
        # Inside a worker job: ctx['redis'] IS an ArqRedis (G5)
        arq = _ctx.get("redis")
    elif app_state is not None:
        arq = getattr(app_state, "arq", None)

    if arq is None:
        raise RuntimeError(
            f"Cannot enqueue job {name!r}: no ARQ connection available (broker down? FR-002a)"
        )

    result = await arq.enqueue_job(name, _job_id=job_id, **kwargs)
    if result is None:
        _log.debug("job.already_queued", job_name=name, job_id=job_id)
    else:
        _log.info("job.enqueued", job_name=name, job_id=job_id)
