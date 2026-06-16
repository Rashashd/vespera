"""FastAPI app factory and lifespan for the guardrails sidecar.

Lifespan: load the service credential (refuse boot if absent) and mark ready. The rails
engine is pure/heuristic — nothing else to warm up.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

_SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'",
}


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Boot: configure logging + load the service token; sets app.state.service_token."""
    from guardrails.core.config import GuardrailsConfig
    from guardrails.core.logging import configure_logging, get_logger
    from guardrails.core.startup import load_guardrails_token

    config: GuardrailsConfig = app.state.config
    configure_logging(config.log_level)
    log = get_logger(__name__)

    app.state.service_token = load_guardrails_token(config)
    log.info("guardrails.ready")

    yield


def create_app() -> FastAPI:
    """Create and configure the guardrails FastAPI application."""
    from guardrails.core.config import get_config
    from guardrails.routes import router

    config = get_config()
    app = FastAPI(title="Pantera Guardrails", version="0.1.0", lifespan=_lifespan)
    app.state.config = config
    app.include_router(router)

    @app.middleware("http")
    async def _security_headers(request: Request, call_next) -> Response:
        response = await call_next(request)
        for name, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    return app


app = create_app()
