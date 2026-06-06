"""ARQ worker skeleton — shares the app's secret/resource bootstrap; no real jobs yet."""

from arq.connections import RedisSettings

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


async def heartbeat(ctx: dict) -> None:
    """Placeholder job so ARQ can start; real pipeline jobs arrive in the scheduling feature."""
    _log.info("worker.heartbeat")


class WorkerSettings:
    """ARQ WorkerSettings skeleton — real jobs/cron and the production broker land in spec 11."""

    functions = [heartbeat]  # ARQ requires >=1 registered; replaced by real jobs in spec 11
    cron_jobs: list = []
    on_startup = startup
    on_shutdown = shutdown
    # Local broker default; spec 11 makes this configurable (rediss:// in production).
    redis_settings = RedisSettings(host="redis", port=6379)
    max_jobs = 10
    job_timeout = 300
    handle_signals = True
