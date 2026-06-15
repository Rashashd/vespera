"""FastAPI application factory: attaches the lifespan and registers routers."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.auth.routes_auth import _users_me_router as auth_me_router
from app.auth.routes_auth import router as auth_router
from app.auth.routes_staff import router as staff_router
from app.clients.routes_client_users import router as client_users_router
from app.clients.routes_clients import router as clients_router
from app.clients.routes_watchlists import router as watchlists_router
from app.core.config import get_settings
from app.core.lifespan import lifespan
from app.embedding.routes import router as embedding_router
from app.ingestion.routes_documents import router as documents_router
from app.ingestion.routes_ingestion import router as ingestion_router
from app.observability.headers import add_security_headers
from app.observability.health import router as health_router
from app.observability.routes import router as usage_router
from app.rag.routes import router as rag_router
from app.reports.metrics_routes import router as metrics_router
from app.reports.passages import router as passages_router
from app.reports.portal_routes import router as portal_router
from app.reports.routes import router as reports_router
from app.triage.routes import router as triage_router


def create_app() -> FastAPI:
    """Create and configure the Pantera FastAPI application."""
    app = FastAPI(title="Pantera", version="0.1.0", lifespan=lifespan)
    app.include_router(health_router)
    app.include_router(auth_router)  # spec 2: /auth/jwt/login (rate-limited), /logout
    app.include_router(auth_me_router)  # spec 4b: PATCH /auth/users/me (self-service pw change)
    app.include_router(staff_router)  # spec 4b: manager-owned staff account CRUD
    app.include_router(clients_router)  # spec 3/4b: client lifecycle + own-client routes
    app.include_router(client_users_router)  # spec 4b: client-user management per named client
    app.include_router(watchlists_router)  # spec 3/4b: /clients/{id}/watchlists CRUD + items
    app.include_router(ingestion_router)  # spec 4/4b: /clients/{id}/watchlists/{id}/ingest + runs
    app.include_router(documents_router)  # spec 4/4b: /clients/{id}/documents browse
    app.include_router(embedding_router)  # spec 6: /clients/{id}/index build + status reads
    app.include_router(rag_router)  # spec 7: /clients/{id}/search RAG retrieval
    app.include_router(triage_router)  # spec 8: /clients/{id}/findings/{id} triage state
    app.include_router(reports_router)  # spec 9: reviewer queue, HITL actions, batch consolidation
    app.include_router(passages_router)  # spec 10: GET /clients/{id}/passages/{chunk_id}
    app.include_router(portal_router)  # spec 10: portal reports (FR-030) + findings (FR-031)
    app.include_router(metrics_router)  # spec 10: GET /clients/{id}/metrics ops dashboard
    app.include_router(usage_router)  # spec 10: GET /clients/{id}/usage cost dashboard
    # Rate-limit machinery (FR-011): a default in-memory limiter so the middleware works
    # before startup; the lifespan upgrades app.state.limiter to the Redis-backed one.
    app.state.limiter = Limiter(key_func=get_remote_address)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    add_security_headers(app)  # baseline HSTS / frame / nosniff / referrer / CSP (FR-010)
    # CORS so the browser SPA (separate origin) can call the API. Added last → outermost,
    # so it answers preflight OPTIONS before auth/rate-limit. Bearer tokens (no cookies) ⇒
    # credentials not required. Origins are config-driven (Settings.cors_allow_origins).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_allow_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return app


app = create_app()
