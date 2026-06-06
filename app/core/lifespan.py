"""Application lifespan: ordered startup (secrets first) and clean shutdown."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

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
    limiter = build_limiter(settings.redis_url)

    # 3. Fail-fast validation before serving.
    await run_startup_checks(engine, redis, settings)

    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    app.state.redis = redis
    app.state.llm = llm
    app.state.dispatcher = dispatcher
    app.state.limiter = limiter
    _log.info("startup.complete", provider=llm.provider, model=llm.model)

    try:
        yield
    finally:
        await engine.dispose()
        await redis.aclose()
        _log.info("shutdown.complete")
