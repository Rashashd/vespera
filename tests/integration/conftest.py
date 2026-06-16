"""Shared fixtures for integration tests (live stack; skipped without PANTERA_INTEGRATION)."""

import os
import uuid
from datetime import UTC

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

_INTEGRATION = bool(os.getenv("PANTERA_INTEGRATION"))


@pytest_asyncio.fixture
async def auth_app():
    """Create the app and run its ordered lifespan (secrets, engine, redis, limiter)."""
    from app.auth.rate_limit import login_limiter
    from app.db.rls import install_system_rls
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        # Spec 12: the runtime engine now enforces RLS (pantera_app role). Many tests open
        # sessions directly via state.session_factory to set up data WITHOUT a request principal;
        # default those to system context so setup writes succeed. Request-path sessions still
        # override per-principal in current_active_principal, so isolation tests stay valid (the
        # dedicated test_rls_isolation builds its own listener-free engine to assert default-deny).
        install_system_rls(app.state.engine)
        # Clear the per-IP login counter so tests don't exhaust each other's 5/min budget.
        login_limiter.reset()
        yield app


@pytest_asyncio.fixture
async def client(auth_app):
    """An ASGI client bound to the running app."""
    transport = ASGITransport(app=auth_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def priv_factory(auth_app):
    """Privileged (RLS-bypassing) session factory for test data setup/teardown.

    The app's own session_factory now connects as the least-privilege pantera_app role (RLS
    enforced), so direct fixture INSERT/DELETE need the privileged role — mirroring how seed
    scripts run (spec 12). Request-path behaviour is still exercised through the ASGI `client`,
    which uses the RLS-enforced engine.
    """
    from app.db.base import create_engine, create_session_factory

    engine = create_engine(auth_app.state.settings.database_url)
    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()


async def _ensure_client(session, client_id: int) -> None:
    """Ensure a clients row exists for the FK users.client_id → clients.id."""
    from app.clients.models import Client

    if await session.get(Client, client_id) is None:
        session.add(Client(id=client_id, name=f"Client {client_id}", status="active"))
        await session.flush()


@pytest_asyncio.fixture
async def make_user(auth_app, priv_factory):
    """Factory that inserts a user directly in the DB; cleans up users + their audit rows.

    user_type inference: if client_id is not None → 'client' (for legacy spec-3/4 tests that
    scope routes by user.client_id); if client_id is None → 'staff' (new agency model).
    Pass user_type explicitly to override.
    """
    from app.audit.models import AuditLog
    from app.auth.backend import password_helper
    from app.auth.models import User

    factory = priv_factory
    created_ids: list[int] = []

    async def _make(
        email: str | None = None,
        password: str = "Abcdef1!",
        role: str = "reviewer",
        client_id: int | None = 1,
        is_active: bool = True,
        user_type: str | None = None,
    ) -> User:
        email = (email or f"{uuid.uuid4().hex}@x.com").lower()
        # Infer user_type from client_id when not explicit (backwards compat for old tests).
        if user_type is None:
            user_type = "client" if client_id is not None else "staff"
        async with factory() as s:
            async with s.begin():
                if client_id is not None:
                    await _ensure_client(s, client_id)
                user = User(
                    email=email,
                    hashed_password=password_helper.hash(password),
                    role=role,
                    user_type=user_type,
                    client_id=client_id,
                    is_active=is_active,
                    is_superuser=False,
                    is_verified=True,
                )
                s.add(user)
            await s.refresh(user)
        created_ids.append(user.id)
        return user

    yield _make

    async with factory() as s:
        async with s.begin():
            if created_ids:
                await s.execute(delete(AuditLog).where(AuditLog.actor_user_id.in_(created_ids)))
                await s.execute(delete(User).where(User.id.in_(created_ids)))


@pytest_asyncio.fixture
async def make_staff_user(auth_app, priv_factory):
    """Factory for staff users (user_type='staff', client_id=None); convenience wrapper."""
    from app.audit.models import AuditLog
    from app.auth.backend import password_helper
    from app.auth.models import User

    factory = priv_factory
    created_ids: list[int] = []

    async def _make(
        email: str | None = None,
        password: str = "Abcdef1!",
        role: str = "reviewer",
        is_active: bool = True,
    ) -> User:
        email = (email or f"{uuid.uuid4().hex}@x.com").lower()
        async with factory() as s:
            async with s.begin():
                user = User(
                    email=email,
                    hashed_password=password_helper.hash(password),
                    role=role,
                    user_type="staff",
                    client_id=None,
                    is_active=is_active,
                    is_superuser=False,
                    is_verified=True,
                )
                s.add(user)
            await s.refresh(user)
        created_ids.append(user.id)
        return user

    yield _make

    async with factory() as s:
        async with s.begin():
            if created_ids:
                await s.execute(delete(AuditLog).where(AuditLog.actor_user_id.in_(created_ids)))
                await s.execute(delete(User).where(User.id.in_(created_ids)))


@pytest_asyncio.fixture
async def make_client(auth_app, priv_factory):
    """Factory that inserts a client row and tears down its watchlists/users/audit on exit."""
    from app.audit.models import AuditLog
    from app.auth.models import User
    from app.clients.models import (
        Client,
        Watchlist,
        WatchlistBudgetUsage,
        WatchlistItem,
    )

    factory = priv_factory
    created_ids: list[int] = []

    async def _make(name: str | None = None, status: str = "active") -> Client:
        name = name or f"C-{uuid.uuid4().hex[:12]}"
        async with factory() as s:
            async with s.begin():
                client = Client(name=name, status=status)
                s.add(client)
            await s.refresh(client)
        created_ids.append(client.id)
        return client

    yield _make

    if not created_ids:
        return
    # Spec-6 embedding rows: chunks cascade on client delete, but index_build_runs has no
    # ON DELETE CASCADE on client_id, so it must be removed before the client row.
    from app.embedding.models import Chunk, DocumentIndexState, IndexBuildRun

    async with factory() as s:
        async with s.begin():
            await s.execute(delete(Chunk).where(Chunk.client_id.in_(created_ids)))
            await s.execute(
                delete(DocumentIndexState).where(DocumentIndexState.client_id.in_(created_ids))
            )
            await s.execute(delete(IndexBuildRun).where(IndexBuildRun.client_id.in_(created_ids)))
            await s.execute(
                delete(WatchlistBudgetUsage).where(WatchlistBudgetUsage.client_id.in_(created_ids))
            )
            await s.execute(delete(WatchlistItem).where(WatchlistItem.client_id.in_(created_ids)))
            await s.execute(delete(Watchlist).where(Watchlist.client_id.in_(created_ids)))
            await s.execute(delete(AuditLog).where(AuditLog.client_id.in_(created_ids)))
            await s.execute(delete(User).where(User.client_id.in_(created_ids)))
            await s.execute(delete(Client).where(Client.id.in_(created_ids)))


@pytest_asyncio.fixture
async def make_watchlist(auth_app, priv_factory):
    """Factory that inserts a watchlist row for a client."""
    from app.clients.models import Watchlist

    factory = priv_factory
    created_ids: list[int] = []

    async def _make(
        client_id: int,
        name: str | None = None,
        is_active: bool = True,
    ) -> Watchlist:
        name = name or f"WL-{uuid.uuid4().hex[:8]}"
        async with factory() as s:
            async with s.begin():
                watchlist = Watchlist(
                    client_id=client_id,
                    name=name,
                    is_active=is_active,
                    cadence="weekly",
                    severity_threshold="serious",
                )
                s.add(watchlist)
            await s.refresh(watchlist)
        created_ids.append(watchlist.id)
        return watchlist

    yield _make

    if created_ids:
        from app.clients.models import Watchlist, WatchlistBudgetUsage, WatchlistItem

        async with factory() as s:
            async with s.begin():
                await s.execute(
                    delete(WatchlistBudgetUsage).where(
                        WatchlistBudgetUsage.watchlist_id.in_(created_ids)
                    )
                )
                await s.execute(
                    delete(WatchlistItem).where(WatchlistItem.watchlist_id.in_(created_ids))
                )
                await s.execute(delete(Watchlist).where(Watchlist.id.in_(created_ids)))


@pytest_asyncio.fixture
async def make_document(auth_app, priv_factory):
    """Factory that inserts a document with a source payload."""
    from datetime import datetime

    from app.ingestion.models import Document, DocumentSource, DocumentWatchlist

    factory = priv_factory
    created_ids: list[int] = []

    async def _make(
        client_id: int,
        source_name: str = "pubmed",
        source_payload: str | dict | None = None,
        title: str | None = None,
        published_at: datetime | None = None,
        source_reliability: str = "peer_reviewed",
        watchlist_id: int | None = None,
    ) -> Document:
        # raw_payload is a JSONB column: a Python str round-trips as a JSON string scalar
        # (what the XML parsers want); a dict round-trips as a JSON object (what FAERS wants).
        if source_payload is None:
            source_payload = {"test": "data"}

        title = title or f"Test Document {uuid.uuid4().hex[:8]}"
        published_at = published_at or datetime.now(UTC)
        unique = uuid.uuid4().hex

        async with factory() as s:
            async with s.begin():
                doc = Document(
                    client_id=client_id,
                    normalized_external_id=f"test-{unique}",
                    source_reliability=source_reliability,
                    title=title,
                    summary="Test summary",
                    published_at=published_at,
                )
                s.add(doc)
                await s.flush()

                ds = DocumentSource(
                    document_id=doc.id,
                    client_id=client_id,
                    source=source_name,
                    source_external_id=f"ext-{unique}",
                    source_reliability=source_reliability,
                    raw_payload=source_payload,
                    fetched_at=datetime.now(UTC),
                )
                s.add(ds)

                # Optionally link the document to a watchlist (committed here so the
                # runner's own sessions can see it — FR-020).
                if watchlist_id is not None:
                    s.add(
                        DocumentWatchlist(
                            document_id=doc.id,
                            watchlist_id=watchlist_id,
                            client_id=client_id,
                        )
                    )
                await s.flush()
                await s.refresh(doc)

        created_ids.append(doc.id)
        return doc

    yield _make

    if created_ids:
        from app.ingestion.models import Document, DocumentSource, DocumentWatchlist

        async with factory() as s:
            async with s.begin():
                await s.execute(
                    delete(DocumentWatchlist).where(DocumentWatchlist.document_id.in_(created_ids))
                )
                await s.execute(
                    delete(DocumentSource).where(DocumentSource.document_id.in_(created_ids))
                )
                await s.execute(delete(Document).where(Document.id.in_(created_ids)))


@pytest_asyncio.fixture
async def async_session(auth_app, priv_factory):
    """Provide a direct async database session for tests."""
    factory = priv_factory
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def mock_modelserver_client():
    """Mock ModelserverClient that returns dummy embeddings."""
    from app.infra.modelserver_client import ModelserverClient

    class MockModelserverClient(ModelserverClient):
        async def embed_chunked(self, texts: list[str]) -> list[dict]:
            """Return dummy 768-dim embeddings for testing."""
            import numpy as np

            results = []
            for text in texts:
                # Deterministic embedding based on text hash
                seed = hash(text) % 2**31
                np.random.seed(seed)
                embedding = np.random.randn(768).astype(np.float32)
                # L2 normalize
                embedding = embedding / (np.linalg.norm(embedding) + 1e-8)
                results.append(
                    {
                        "embedding": embedding.tolist(),
                        "model_version": {"sha256": "test-model-sha256"},
                    }
                )
            return results

        async def get_ready(self) -> dict:
            """Return mock ready response."""
            return {"models": {"embedder": {"sha256": "test-model-sha256"}}}

    return MockModelserverClient(base_url="http://test", token="test-token")


async def login_token(client: AsyncClient, email: str, password: str = "Abcdef1!") -> str:
    """Helper: log in and return the bearer access token."""
    resp = await client.post("/auth/jwt/login", data={"username": email, "password": password})
    resp.raise_for_status()
    return resp.json()["access_token"]


@pytest_asyncio.fixture
async def authed_reviewer_client(client, make_staff_user):
    """An ASGI client pre-authenticated as a reviewer (staff). Used by the spec-10 route tests."""
    user = await make_staff_user(role="reviewer")
    token = await login_token(client, user.email)
    client.headers["Authorization"] = f"Bearer {token}"
    return client


@pytest_asyncio.fixture
async def authed_admin_client(client, make_staff_user):
    """An ASGI client pre-authenticated as an admin (staff) — for require_admin routes."""
    user = await make_staff_user(role="admin")
    token = await login_token(client, user.email)
    client.headers["Authorization"] = f"Bearer {token}"
    return client


@pytest_asyncio.fixture
async def authed_manager_client(client, make_staff_user):
    """An ASGI client pre-authenticated as a manager (staff) — for require_manager routes."""
    user = await make_staff_user(role="manager")
    token = await login_token(client, user.email)
    client.headers["Authorization"] = f"Bearer {token}"
    return client
