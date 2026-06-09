"""Acting-client context integration tests (spec 4b, US1; FR-008/FR-021/SC-009)."""

import os
import uuid

import pytest
import pytest_asyncio
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from tests.integration.conftest import login_token

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires the Compose stack (Vault + Postgres + Redis)",
)


@pytest_asyncio.fixture
async def probed_app():
    """App with a demo /clients/{client_id}/probe endpoint that exercises acting_client."""
    from app.auth.dependencies import acting_client, require_admin
    from app.auth.rate_limit import login_limiter
    from app.clients.models import Client
    from app.main import create_app

    app = create_app()

    _get_acting_client = acting_client()
    _get_acting_client_read = acting_client(allow_suspended=True)

    @app.get("/_test/clients/{client_id}/probe")
    async def _probe(
        _: object = Depends(require_admin),
        target: Client = Depends(_get_acting_client),
    ):
        return {"client_id": target.id, "status": target.status}

    @app.get("/_test/clients/{client_id}/probe-read")
    async def _probe_read(
        target: Client = Depends(_get_acting_client_read),
    ):
        return {"client_id": target.id, "status": target.status}

    async with app.router.lifespan_context(app):
        login_limiter.reset()
        yield app


@pytest_asyncio.fixture
async def probed_client(probed_app):
    transport = ASGITransport(app=probed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def make_staff_for_probe(probed_app):
    """Staff user factory scoped to probed_app's session factory."""
    from app.auth.backend import password_helper
    from app.auth.models import User
    from app.db.models import AuditLog

    factory = probed_app.state.session_factory
    created: list[int] = []

    async def _make(role: str = "admin") -> User:
        email = f"{uuid.uuid4().hex}@x.com"
        async with factory() as s:
            async with s.begin():
                user = User(
                    email=email,
                    hashed_password=password_helper.hash("Abcdef1!"),
                    role=role,
                    user_type="staff",
                    client_id=None,
                    is_active=True,
                    is_superuser=False,
                    is_verified=True,
                )
                s.add(user)
            await s.refresh(user)
        created.append(user.id)
        return user

    yield _make

    async with factory() as s:
        async with s.begin():
            if created:
                await s.execute(delete(AuditLog).where(AuditLog.actor_user_id.in_(created)))
                await s.execute(delete(User).where(User.id.in_(created)))


@pytest_asyncio.fixture
async def make_tenant(probed_app):
    """Client factory scoped to probed_app's session factory."""
    from app.auth.models import User
    from app.clients.models import Client, Watchlist, WatchlistBudgetUsage, WatchlistItem
    from app.db.models import AuditLog

    factory = probed_app.state.session_factory
    created: list[int] = []

    async def _make(status: str = "active") -> Client:
        name = f"T-{uuid.uuid4().hex[:10]}"
        async with factory() as s:
            async with s.begin():
                c = Client(name=name, status=status)
                s.add(c)
            await s.refresh(c)
        created.append(c.id)
        return c

    yield _make

    if not created:
        return
    async with factory() as s:
        async with s.begin():
            await s.execute(
                delete(WatchlistBudgetUsage).where(WatchlistBudgetUsage.client_id.in_(created))
            )
            await s.execute(delete(WatchlistItem).where(WatchlistItem.client_id.in_(created)))
            await s.execute(delete(Watchlist).where(Watchlist.client_id.in_(created)))
            await s.execute(delete(AuditLog).where(AuditLog.client_id.in_(created)))
            await s.execute(delete(User).where(User.client_id.in_(created)))
            await s.execute(delete(Client).where(Client.id.in_(created)))


# ---- staff cross-client access -----------------------------------------------


async def test_staff_admin_reaches_any_client(probed_client, make_staff_for_probe, make_tenant):
    """A staff admin can name any valid active client as the acting target (FR-008)."""
    admin = await make_staff_for_probe(role="admin")
    target = await make_tenant()
    token = await login_token(probed_client, admin.email)
    resp = await probed_client.get(
        f"/_test/clients/{target.id}/probe",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["client_id"] == target.id


async def test_non_existent_client_is_404(probed_client, make_staff_for_probe):
    """Naming a non-existent client_id returns 404 CLIENT_NOT_FOUND (FR-008)."""
    admin = await make_staff_for_probe(role="admin")
    token = await login_token(probed_client, admin.email)
    resp = await probed_client.get(
        "/_test/clients/999999999/probe",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "CLIENT_NOT_FOUND"


async def test_suspended_client_new_work_is_400(probed_client, make_staff_for_probe, make_tenant):
    """Naming a suspended client on a new-work route returns 400 CLIENT_SUSPENDED (FR-008)."""
    admin = await make_staff_for_probe(role="admin")
    suspended = await make_tenant(status="suspended")
    token = await login_token(probed_client, admin.email)
    resp = await probed_client.get(
        f"/_test/clients/{suspended.id}/probe",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "CLIENT_SUSPENDED"


async def test_suspended_client_read_allowed(probed_client, make_staff_for_probe, make_tenant):
    """allow_suspended=True lets staff read data of a suspended client (FR-008 read path)."""
    admin = await make_staff_for_probe(role="admin")
    suspended = await make_tenant(status="suspended")
    token = await login_token(probed_client, admin.email)
    resp = await probed_client.get(
        f"/_test/clients/{suspended.id}/probe-read",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "suspended"


async def test_unauthenticated_returns_401(probed_client, make_tenant):
    """No bearer token returns 401 (no client-existence leak)."""
    t = await make_tenant()
    resp = await probed_client.get(f"/_test/clients/{t.id}/probe")
    assert resp.status_code == 401


# ---- client-user own-client restriction (SC-009) ----------------------------


async def test_client_user_cannot_name_other_client(probed_client, make_tenant, probed_app):
    """A client-user cannot name another client's id as acting target (SC-009 / 404 no-leak)."""
    from app.auth.backend import password_helper
    from app.auth.models import User

    client_a = await make_tenant()
    client_b = await make_tenant()
    factory = probed_app.state.session_factory
    pw = "Abcdef1!"
    email = f"{uuid.uuid4().hex}@x.com"
    async with factory() as s:
        async with s.begin():
            user = User(
                email=email,
                hashed_password=password_helper.hash(pw),
                role="client_user",
                user_type="client",
                client_id=client_a.id,
                client_scope="full",
                is_active=True,
                is_superuser=False,
                is_verified=True,
            )
            s.add(user)

    token = await login_token(probed_client, email, pw)
    # Client-user names client_b on a no-role-guard route → 404 (existence not leaked, SC-009).
    # Use probe-read (no require_admin) so acting_client runs before any role check.
    resp = await probed_client.get(
        f"/_test/clients/{client_b.id}/probe-read",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404
    # Client-user names their own client but hits require_admin → 403 (not a staff user)
    resp2 = await probed_client.get(
        f"/_test/clients/{client_a.id}/probe",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp2.status_code == 403
