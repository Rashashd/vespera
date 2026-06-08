"""Application lifespan: ordered startup (secrets first) and clean shutdown."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.audit.handler import register_audit_handlers
from app.auth.rate_limit import use_redis_storage
from app.core.config import get_settings
from app.core.dispatcher import EventDispatcher
from app.core.startup import load_secrets_from_vault, run_startup_checks
from app.db.base import create_engine, create_session_factory
from app.infra.llm_adapter import build_llm_client
from app.infra.redis import create_redis
from app.observability.headers import build_limiter
from app.observability.logging import configure_logging, get_logger
from app.observability.sentry import init_sentry

_log = get_logger(__name__)


async def _run_ingestion_startup(session_factory) -> None:  # type: ignore[type-arg]
    """Verify the bundled MeSH artifact and reconcile interrupted ingestion runs (D8, D11)."""
    # MeSH artifact check (non-fatal).
    try:
        from app.ingestion.mesh import load_mesh_terms

        load_mesh_terms()
        _log.info("mesh.artifact_ok")
    except Exception as exc:  # noqa: BLE001
        _log.warning("mesh.artifact_missing", error=str(exc))

    # Reconcile any lingering `running` runs left by a previous crash (FR-024).
    try:
        from app.ingestion.service import reconcile_interrupted_runs

        async with session_factory() as session:
            async with session.begin():
                count = await reconcile_interrupted_runs(session)
        if count:
            _log.warning("ingestion.reconciled_stale_runs", count=count)
    except Exception as exc:  # noqa: BLE001
        _log.warning("ingestion.reconcile_failed", error=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Load secrets first, then build singletons, validate, serve, and clean up."""
    settings = get_settings()
    configure_logging(settings.log_level)
    init_sentry(settings)  # capture unhandled exceptions (no-op without a DSN)

    # 1. Secrets MUST be loaded before any resource is constructed.
    await load_secrets_from_vault(settings)

    # 2. Build shared singletons exactly once.
    engine = create_engine(settings.database_url)
    redis = await create_redis(settings.redis_url)
    llm = build_llm_client(settings)
    dispatcher = EventDispatcher()
    register_audit_handlers(dispatcher)  # audit log listens to every domain event
    limiter = build_limiter(settings.redis_url)
    use_redis_storage(settings.redis_url)  # spec 2: login limiter enforces against Redis (FR-010)

    # 3. Fail-fast validation before serving.
    await run_startup_checks(engine, redis, settings)

    session_factory = create_session_factory(engine)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.redis = redis
    app.state.llm = llm
    app.state.dispatcher = dispatcher
    app.state.limiter = limiter

    # 4. Ingestion startup: MeSH check + stale-run reconciliation (non-fatal).
    await _run_ingestion_startup(session_factory)

    _log.info("startup.complete", provider=llm.provider, model=llm.model)

    try:
        yield
    finally:
        await engine.dispose()
        await redis.aclose()
        _log.info("shutdown.complete")
