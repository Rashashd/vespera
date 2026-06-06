"""ARQ worker skeleton — shares the app's secret/resource bootstrap; no jobs yet."""

from app.core.config import get_settings
from app.core.startup import load_secrets_from_vault, run_startup_checks
from app.db.base import create_engine
from app.infra.llm_adapter import build_llm_client
from app.infra.redis import create_redis
from app.observability.logging import configure_logging, get_logger

_log = get_logger(__name__)


async def startup(ctx: dict) -> None:
    """Load secrets and build resources identically to the API (FR-020)."""
    settings = get_settings()
    configure_logging(settings.log_level)
    await load_secrets_from_vault(settings)
    ctx["settings"] = settings
    ctx["engine"] = create_engine(settings.database_url)
    ctx["redis"] = await create_redis(settings.redis_url)
    ctx["llm"] = build_llm_client(settings)
    await run_startup_checks(ctx["engine"], ctx["redis"], settings)
    _log.info("worker.startup.complete")


async def shutdown(ctx: dict) -> None:
    """Dispose worker-owned resources cleanly."""
    await ctx["engine"].dispose()
    await ctx["redis"].aclose()
    _log.info("worker.shutdown.complete")


class WorkerSettings:
    """ARQ WorkerSettings skeleton — cron jobs and functions are added in a later feature."""

    functions: list = []
    cron_jobs: list = []
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 10
    job_timeout = 300
    handle_signals = True
