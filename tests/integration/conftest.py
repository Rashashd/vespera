"""Shared fixtures for auth integration tests (live stack; skipped without PANTERA_INTEGRATION)."""

import os
import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

_INTEGRATION = bool(os.getenv("PANTERA_INTEGRATION"))


@pytest_asyncio.fixture
async def auth_app():
    """Create the app and run its ordered lifespan (secrets, engine, redis, limiter)."""
    from app.auth.rate_limit import login_limiter
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        # Clear the per-IP login counter so tests don't exhaust each other's 5/min budget.
        login_limiter.reset()
        yield app


@pytest_asyncio.fixture
async def client(auth_app):
    """An ASGI client bound to the running app."""
    transport = ASGITransport(app=auth_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _ensure_client(session, client_id: int) -> None:
    """Ensure a clients row exists for the FK users.client_id → clients.id (spec 3)."""
    from app.clients.models import Client

    if await session.get(Client, client_id) is None:
        session.add(Client(id=client_id, name=f"Client {client_id}", status="active"))
        await session.flush()


@pytest_asyncio.fixture
async def make_user(auth_app):
    """Factory that inserts a user directly in the DB; cleans up users + their audit rows."""
    from app.auth.backend import password_helper
    from app.auth.models import User
    from app.db.models import AuditLog

    factory = auth_app.state.session_factory
    created_ids: list[int] = []

    async def _make(
        email: str | None = None,
        password: str = "Abcdef1!",
        role: str = "reviewer",
        client_id: int = 1,
        is_active: bool = True,
    ) -> User:
        email = (email or f"{uuid.uuid4().hex}@x.com").lower()
        async with factory() as s:
            async with s.begin():
                await _ensure_client(s, client_id)  # satisfy the FK before inserting the user
                user = User(
                    email=email,
                    hashed_password=password_helper.hash(password),
                    role=role,
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
async def make_client(auth_app):
    """Factory that inserts a client row and tears down its watchlists/users/audit on exit."""
    from app.auth.models import User
    from app.clients.models import (
        Client,
        Watchlist,
        WatchlistBudgetUsage,
        WatchlistItem,
    )
    from app.db.models import AuditLog

    factory = auth_app.state.session_factory
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
    async with factory() as s:
        async with s.begin():
            await s.execute(
                delete(WatchlistBudgetUsage).where(WatchlistBudgetUsage.client_id.in_(created_ids))
            )
            await s.execute(delete(WatchlistItem).where(WatchlistItem.client_id.in_(created_ids)))
            await s.execute(delete(Watchlist).where(Watchlist.client_id.in_(created_ids)))
            await s.execute(delete(AuditLog).where(AuditLog.client_id.in_(created_ids)))
            await s.execute(delete(User).where(User.client_id.in_(created_ids)))
            await s.execute(delete(Client).where(Client.id.in_(created_ids)))


async def login_token(client: AsyncClient, email: str, password: str = "Abcdef1!") -> str:
    """Helper: log in and return the bearer access token."""
    resp = await client.post("/auth/jwt/login", data={"username": email, "password": password})
    resp.raise_for_status()
    return resp.json()["access_token"]
