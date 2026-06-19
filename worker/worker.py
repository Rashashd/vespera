"""ARQ worker: secrets bootstrap, dispatcher/session_factory, real pipeline jobs + cron."""

from arq.connections import RedisSettings

from app.audit.handler import register_audit_handlers
from app.core.config import get_settings
from app.core.dispatcher import EventDispatcher
from app.core.startup import load_secrets_from_vault, run_startup_checks
from app.db.base import create_engine, create_session_factory
from app.db.rls import install_system_rls
from app.infra.llm_adapter import build_llm_client
from app.infra.redis import create_redis
from app.observability.logging import configure_logging, get_logger

_log = get_logger(__name__)


async def startup(ctx: dict) -> None:
    """Load secrets and build all resources (mirrors app/core/lifespan.py:62-81)."""
    settings = get_settings()
    configure_logging(settings.log_level)
    await load_secrets_from_vault(settings)
    ctx["settings"] = settings

    # Spec 13 US8: configure LangSmith tracing for the worker pipeline (mirrors lifespan.py).
    # OFF by default — no-op unless tracing_enabled AND a key are set; traces are PII-free.
    from app.observability.tracing import configure_tracing

    configure_tracing(settings)

    engine = create_engine(settings.app_database_url)  # least-priv runtime role (RLS-enforced)
    install_system_rls(engine)  # all worker sessions run as system (is_staff) — covers the pipeline
    ctx["engine"] = engine
    ctx["redis"] = await create_redis(settings.redis_url)
    ctx["llm"] = build_llm_client(settings)

    # Build dispatcher + register audit handlers so every job emits audit rows (spec 11 §3).
    dispatcher = EventDispatcher()
    register_audit_handlers(dispatcher)
    # Spec 13 US6: budget-threshold crossings (raised in task_consolidate's gate) notify staff.
    from app.delivery.notifications import register_budget_notifications

    register_budget_notifications(dispatcher)
    ctx["dispatcher"] = dispatcher

    ctx["session_factory"] = create_session_factory(engine)

    await run_startup_checks(engine, ctx["redis"], settings)
    _log.info("worker.startup.complete")


async def shutdown(ctx: dict) -> None:
    """Dispose worker-owned resources cleanly."""
    await ctx["engine"].dispose()
    await ctx["redis"].aclose()
    _log.info("worker.shutdown.complete")


def _make_redis_settings() -> RedisSettings:
    """Derive RedisSettings from settings.redis_url; falls back to redis:6379 (FR-023)."""
    url = get_settings().redis_url
    if url:
        return RedisSettings.from_dsn(url)
    return RedisSettings(host="redis", port=6379)


# ── Import tasks/cron after helpers are defined ───────────────────────────────
from app.jobs.dead_letter import purge_expired  # noqa: E402
from app.jobs.scheduler import scheduler_tick  # noqa: E402
from app.jobs.tasks import (  # noqa: E402
    task_consolidate,
    task_cycle_start,
    task_deliver_report,
    task_delivery_sla_sweep,
    task_expedited,
    task_index_build,
    task_redraft,
    task_run_ingestion,
)

_settings = get_settings()

try:
    from arq import cron as _arq_cron

    # Sweep cadence: fire at every Nth minute of the hour (default every 15 min).
    _sweep_minutes = set(range(0, 60, max(1, _settings.delivery_sweep_interval_minutes)))

    _cron_jobs = [
        _arq_cron(scheduler_tick, minute=_settings.scheduler_tick_cron_minute),
        _arq_cron(purge_expired, hour=3, minute=0),
        _arq_cron(task_delivery_sla_sweep, minute=_sweep_minutes),
    ]
except Exception:  # arq not available during unit tests
    _cron_jobs = []


class WorkerSettings:
    """ARQ WorkerSettings: real pipeline jobs, cron, and TLS-capable broker (spec 11)."""

    functions = [
        task_run_ingestion,
        task_index_build,
        task_expedited,
        task_redraft,
        task_consolidate,
        task_cycle_start,
        task_deliver_report,
        purge_expired,
    ]
    cron_jobs = _cron_jobs

    on_startup = startup
    on_shutdown = shutdown

    # Derived at class-definition time; REDIS_URL env var is available before Vault loads.
    redis_settings = _make_redis_settings()

    max_jobs = _settings.worker_max_jobs
    job_timeout = _settings.worker_job_timeout
    max_tries = 3
    handle_signals = True
    keep_result = 3600  # keep results 1h for observability
