"""FastAPI application factory: attaches the lifespan and registers routers."""

from fastapi import FastAPI
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.api import health
from app.auth.routes_auth import router as auth_router
from app.auth.routes_users import router as users_router
from app.clients.routes_clients import router as clients_router
from app.clients.routes_watchlists import router as watchlists_router
from app.core.lifespan import lifespan
from app.ingestion.routes_documents import router as documents_router
from app.ingestion.routes_ingestion import router as ingestion_router
from app.observability.headers import add_security_headers


def create_app() -> FastAPI:
    """Create and configure the Pantera FastAPI application."""
    app = FastAPI(title="Pantera", version="0.1.0", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(auth_router)  # spec 2: /auth/jwt/login (rate-limited), /logout
    app.include_router(users_router)  # spec 2: admin user management (client-scoped)
    app.include_router(clients_router)  # spec 3: GET/PATCH own client
    app.include_router(watchlists_router)  # spec 3: watchlist CRUD + items + per-watchlist config
    app.include_router(ingestion_router)  # spec 4: trigger + run-status endpoints
    app.include_router(documents_router)  # spec 4: document browse endpoints
    # Rate-limit machinery (FR-011): a default in-memory limiter so the middleware works
    # before startup; the lifespan upgrades app.state.limiter to the Redis-backed one.
    app.state.limiter = Limiter(key_func=get_remote_address)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    add_security_headers(app)  # baseline HSTS / frame / nosniff / referrer / CSP (FR-010)
    return app


app = create_app()
