"""Client lifecycle integration tests (spec 4b, US2; FR-011/FR-012)."""

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete

from tests.integration.conftest import login_token

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires the Compose stack (Vault + Postgres + Redis)",
)


@pytest_asyncio.fixture
async def api_client_tracker(auth_app):
    """Collect client IDs created via the API; tears them down after the test."""
    from app.audit.models import AuditLog
    from app.auth.models import User
    from app.clients.models import Client, Watchlist, WatchlistBudgetUsage, WatchlistItem

    ids: list[int] = []

    async def _track(client_id: int) -> None:
        ids.append(client_id)

    yield _track

    if not ids:
        return
    factory = auth_app.state.session_factory
    async with factory() as s:
        async with s.begin():
            await s.execute(
                delete(WatchlistBudgetUsage).where(WatchlistBudgetUsage.client_id.in_(ids))
            )
            await s.execute(delete(WatchlistItem).where(WatchlistItem.client_id.in_(ids)))
            await s.execute(delete(Watchlist).where(Watchlist.client_id.in_(ids)))
            await s.execute(delete(AuditLog).where(AuditLog.client_id.in_(ids)))
            await s.execute(delete(User).where(User.client_id.in_(ids)))
            await s.execute(delete(Client).where(Client.id.in_(ids)))


# ---- roster listing ----------------------------------------------------------


async def test_staff_reviewer_can_list_clients(client, make_staff_user, make_client):
    """Any staff role (including reviewer) can read the client roster (FR-008)."""
    reviewer = await make_staff_user(role="reviewer")
    target = await make_client()
    token = await login_token(client, reviewer.email)
    resp = await client.get("/clients", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    ids = {c["id"] for c in resp.json()}
    assert target.id in ids


async def test_client_user_cannot_list_clients(client, make_client, auth_app):
    """Client-users are not staff; GET /clients returns 403 for them."""
    from app.auth.backend import password_helper
    from app.auth.models import User

    target = await make_client()
    factory = auth_app.state.session_factory
    pw = "Abcdef1!"
    email = f"{uuid.uuid4().hex}@x.com"
    async with factory() as s:
        async with s.begin():
            user = User(
                email=email,
                hashed_password=password_helper.hash(pw),
                role="client_user",
                user_type="client",
                client_id=target.id,
                client_scope="full",
                is_active=True,
                is_superuser=False,
                is_verified=True,
            )
            s.add(user)
    token = await login_token(client, email, pw)
    resp = await client.get("/clients", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


async def test_staff_can_get_client_detail(client, make_staff_user, make_client):
    """Staff can retrieve a named client's full detail including email fields (FR-008)."""
    admin = await make_staff_user(role="admin")
    target = await make_client()
    token = await login_token(client, admin.email)
    resp = await client.get(f"/clients/{target.id}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == target.id
    assert "urgent_severity_threshold" in body


# ---- client creation ---------------------------------------------------------


async def test_manager_creates_client(client, make_staff_user, api_client_tracker):
    """Manager can create a client via POST /clients (FR-011)."""
    manager = await make_staff_user(role="manager")
    token = await login_token(client, manager.email)
    name = f"LC-{uuid.uuid4().hex[:10]}"
    resp = await client.post(
        "/clients",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": name},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == name
    assert body["status"] == "active"
    assert "report_email_regular" in body
    await api_client_tracker(body["id"])


async def test_duplicate_name_rejected(client, make_staff_user, make_client):
    """Duplicate client name (case-insensitive) is rejected with 409 (FR-001)."""
    manager = await make_staff_user(role="manager")
    await make_client(name="DupeTestClient")
    token = await login_token(client, manager.email)
    resp = await client.post(
        "/clients",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "DupeTestClient"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "CLIENT_NAME_TAKEN"


async def test_non_manager_cannot_create_client(client, make_staff_user):
    """Staff admin cannot create a client (manager-only; contracts/client-lifecycle.md)."""
    admin = await make_staff_user(role="admin")
    token = await login_token(client, admin.email)
    resp = await client.post(
        "/clients",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": f"LC-{uuid.uuid4().hex[:10]}"},
    )
    assert resp.status_code == 403


async def test_invalid_report_email_rejected(client, make_staff_user):
    """Malformed report_email_regular is rejected with 400 INVALID_EMAIL."""
    manager = await make_staff_user(role="manager")
    token = await login_token(client, manager.email)
    resp = await client.post(
        "/clients",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": f"LC-{uuid.uuid4().hex[:10]}",
            "report_email_regular": "not-an-email",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "INVALID_EMAIL"


# ---- lifecycle: suspend / reactivate ----------------------------------------


async def test_manager_suspends_client(client, make_staff_user, make_client):
    """Manager can suspend a client; status changes to 'suspended' (FR-011)."""
    manager = await make_staff_user(role="manager")
    target = await make_client()
    token = await login_token(client, manager.email)
    resp = await client.post(
        f"/clients/{target.id}/suspend",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "suspended"


async def test_suspend_is_idempotent(client, make_staff_user, make_client):
    """Suspending an already-suspended client returns 200 unchanged (idempotent; FR-011)."""
    manager = await make_staff_user(role="manager")
    target = await make_client(status="suspended")
    token = await login_token(client, manager.email)
    resp = await client.post(
        f"/clients/{target.id}/suspend",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "suspended"


async def test_manager_reactivates_client(client, make_staff_user, make_client):
    """Manager can reactivate a suspended client (FR-011)."""
    manager = await make_staff_user(role="manager")
    target = await make_client(status="suspended")
    token = await login_token(client, manager.email)
    resp = await client.post(
        f"/clients/{target.id}/reactivate",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"


async def test_non_manager_cannot_suspend(client, make_staff_user, make_client):
    """Staff admin cannot suspend a client (manager-only; contracts/client-lifecycle.md)."""
    admin = await make_staff_user(role="admin")
    target = await make_client()
    token = await login_token(client, admin.email)
    resp = await client.post(
        f"/clients/{target.id}/suspend",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_no_hard_delete_endpoint(client, make_staff_user, make_client):
    """There is no DELETE /clients/{id} endpoint; method not allowed (FR-012)."""
    manager = await make_staff_user(role="manager")
    target = await make_client()
    token = await login_token(client, manager.email)
    resp = await client.delete(
        f"/clients/{target.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 405
