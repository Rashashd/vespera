"""FastAPI application factory: attaches the lifespan and registers routers."""

from fastapi import FastAPI

from app.api import health
from app.core.lifespan import lifespan


def create_app() -> FastAPI:
    """Create and configure the Pantera FastAPI application."""
    app = FastAPI(title="Pantera", version="0.1.0", lifespan=lifespan)
    app.include_router(health.router)
    # Security-headers middleware, Sentry, and the rate-limit capability are added in
    # the US3/US5 phases.
    return app


app = create_app()
