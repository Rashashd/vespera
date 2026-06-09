"""Client-side user management integration tests (spec 4b, US3; FR-014/FR-015)."""

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


def _email() -> str:
    return f"{uuid.uuid4().hex}@x.com"


@pytest_asyncio.fixture
async def watchlist_for_client(auth_app):
    """Create a minimal watchlist row for a given client; cleans up on exit."""
    from app.clients.models import Watchlist, WatchlistItem

    factory = auth_app.state.session_factory
    created_ids: list[int] = []

    async def _make(client_id: int) -> int:
        async with factory() as s:
            async with s.begin():
                wl = Watchlist(
                    client_id=client_id,
                    name=f"WL-{uuid.uuid4().hex[:8]}",
                    cadence="weekly",
                    severity_threshold="serious",
                    is_active=True,
                )
                s.add(wl)
            await s.refresh(wl)
        created_ids.append(wl.id)
        return wl.id

    yield _make

    if not created_ids:
        return
    async with factory() as s:
        async with s.begin():
            await s.execute(
                delete(WatchlistItem).where(WatchlistItem.watchlist_id.in_(created_ids))
            )
            await s.execute(delete(Watchlist).where(Watchlist.id.in_(created_ids)))


# ---- creation ----------------------------------------------------------------


async def test_admin_creates_full_client_user(client, make_staff_user, make_client):
    """Admin can create a full-scope client-user (no watchlist/severity constraints)."""
    admin = await make_staff_user(role="admin")
    target = await make_client()
    token = await login_token(client, admin.email)
    resp = await client.post(
        f"/clients/{target.id}/users",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": _email(), "password": "Abcdef1!", "client_scope": "full"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["client_id"] == target.id
    assert body["role"] == "client_user"
    assert body["client_scope"] == "full"
    assert body["watchlist_ids"] == []
    assert "password" not in body


async def test_admin_creates_scoped_client_user_with_severity(client, make_staff_user, make_client):
    """Admin can create a scoped user with min_severity (no watchlist needed)."""
    admin = await make_staff_user(role="admin")
    target = await make_client()
    token = await login_token(client, admin.email)
    resp = await client.post(
        f"/clients/{target.id}/users",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "email": _email(),
            "password": "Abcdef1!",
            "client_scope": "scoped",
            "min_severity": "serious",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["min_severity"] == "serious"


async def test_admin_creates_scoped_user_with_watchlist(
    client, make_staff_user, make_client, watchlist_for_client
):
    """Admin can create a scoped user with a valid watchlist (no severity needed)."""
    admin = await make_staff_user(role="admin")
    target = await make_client()
    wl_id = await watchlist_for_client(target.id)
    token = await login_token(client, admin.email)
    resp = await client.post(
        f"/clients/{target.id}/users",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "email": _email(),
            "password": "Abcdef1!",
            "client_scope": "scoped",
            "watchlist_ids": [wl_id],
        },
    )
    assert resp.status_code == 201
    assert resp.json()["watchlist_ids"] == [wl_id]


async def test_scoped_without_constraints_rejected(client, make_staff_user, make_client):
    """Scoped creation without severity or watchlist_ids → 400 SCOPE_REQUIRED (FR-014)."""
    admin = await make_staff_user(role="admin")
    target = await make_client()
    token = await login_token(client, admin.email)
    resp = await client.post(
        f"/clients/{target.id}/users",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": _email(), "password": "Abcdef1!", "client_scope": "scoped"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "SCOPE_REQUIRED"


async def test_cross_client_watchlist_rejected(
    client, make_staff_user, make_client, watchlist_for_client
):
    """Watchlist belonging to another client is rejected with 400 CROSS_CLIENT_WATCHLIST."""
    admin = await make_staff_user(role="admin")
    target_client = await make_client()
    other_client = await make_client()
    other_wl_id = await watchlist_for_client(other_client.id)
    token = await login_token(client, admin.email)
    resp = await client.post(
        f"/clients/{target_client.id}/users",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "email": _email(),
            "password": "Abcdef1!",
            "client_scope": "scoped",
            "watchlist_ids": [other_wl_id],
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "CROSS_CLIENT_WATCHLIST"


async def test_reviewer_cannot_create_client_user(client, make_staff_user, make_client):
    """Reviewer does not have admin access; POST /clients/{id}/users → 403."""
    reviewer = await make_staff_user(role="reviewer")
    target = await make_client()
    token = await login_token(client, reviewer.email)
    resp = await client.post(
        f"/clients/{target.id}/users",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": _email(), "password": "Abcdef1!", "client_scope": "full"},
    )
    assert resp.status_code == 403


async def test_duplicate_email_rejected(client, make_staff_user, make_client):
    """Creating a user with an already-registered email → 409 USER_ALREADY_EXISTS."""
    admin = await make_staff_user(role="admin")
    target = await make_client()
    email = _email()
    token = await login_token(client, admin.email)
    await client.post(
        f"/clients/{target.id}/users",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": email, "password": "Abcdef1!", "client_scope": "full"},
    )
    resp = await client.post(
        f"/clients/{target.id}/users",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": email, "password": "Abcdef1!", "client_scope": "full"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "USER_ALREADY_EXISTS"


# ---- listing -----------------------------------------------------------------


async def test_admin_lists_client_users(client, make_staff_user, make_client):
    """Admin can list client-users for a named client."""
    admin = await make_staff_user(role="admin")
    target = await make_client()
    token = await login_token(client, admin.email)
    # Create one user first
    await client.post(
        f"/clients/{target.id}/users",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": _email(), "password": "Abcdef1!", "client_scope": "full"},
    )
    resp = await client.get(
        f"/clients/{target.id}/users", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


# ---- scope update ------------------------------------------------------------


async def test_admin_changes_scope(client, make_staff_user, make_client):
    """Admin can update a client-user's scope from full to scoped+severity."""
    admin = await make_staff_user(role="admin")
    target = await make_client()
    token = await login_token(client, admin.email)
    create_resp = await client.post(
        f"/clients/{target.id}/users",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": _email(), "password": "Abcdef1!", "client_scope": "full"},
    )
    user_id = create_resp.json()["id"]
    patch_resp = await client.patch(
        f"/clients/{target.id}/users/{user_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"client_scope": "scoped", "min_severity": "serious"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["client_scope"] == "scoped"
    assert patch_resp.json()["min_severity"] == "serious"


async def test_admin_deactivates_client_user(client, make_staff_user, make_client):
    """Admin can deactivate a client-user."""
    admin = await make_staff_user(role="admin")
    target = await make_client()
    token = await login_token(client, admin.email)
    create_resp = await client.post(
        f"/clients/{target.id}/users",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": _email(), "password": "Abcdef1!", "client_scope": "full"},
    )
    user_id = create_resp.json()["id"]
    patch_resp = await client.patch(
        f"/clients/{target.id}/users/{user_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"is_active": False},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["is_active"] is False
