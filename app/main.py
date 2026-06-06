"""FastAPI application factory: attaches the lifespan and registers routers."""

from fastapi import FastAPI
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.api import health
from app.core.lifespan import lifespan


def create_app() -> FastAPI:
    """Create and configure the Pantera FastAPI application."""
    app = FastAPI(title="Pantera", version="0.1.0", lifespan=lifespan)
    app.include_router(health.router)
    # Rate-limit machinery (FR-011): a default in-memory limiter so the middleware works
    # before startup; the lifespan upgrades app.state.limiter to the Redis-backed one.
    app.state.limiter = Limiter(key_func=get_remote_address)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    # Security-response headers are added in the US5 phase.
    return app


app = create_app()
