"""Admin user-management integration tests: scoping, last-admin, escalation (US3)."""

import os
import uuid

import pytest

from tests.integration.conftest import login_token

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires the Compose stack (Vault + Postgres + Redis)",
)


def _email() -> str:
    return f"{uuid.uuid4().hex}@x.com"


async def test_admin_creates_user_in_own_client(client, make_user):
    """Created users belong to the admin's client and can authenticate (FR-006/007)."""
    admin = await make_user(role="admin", client_id=1)
    token = await login_token(client, admin.email)
    new_email = _email()
    resp = await client.post(
        "/users",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": new_email, "password": "Abcdef1!", "role": "reviewer"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["client_id"] == 1
    assert body["role"] == "reviewer"
    assert "password" not in body and "hashed_password" not in body
    # the new reviewer can log in
    assert (
        await client.post("/auth/jwt/login", data={"username": new_email, "password": "Abcdef1!"})
    ).status_code == 200


async def test_weak_password_rejected(client, make_user):
    """Creating a user with a non-conforming password is rejected (FR-016)."""
    admin = await make_user(role="admin")
    token = await login_token(client, admin.email)
    resp = await client.post(
        "/users",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": _email(), "password": "weak", "role": "reviewer"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"].startswith("PASSWORD_POLICY")


async def test_duplicate_email_conflict(client, make_user):
    """A globally-duplicate email is rejected with 409 (FR-007/D12)."""
    admin = await make_user(role="admin")
    existing = await make_user(role="reviewer")
    token = await login_token(client, admin.email)
    resp = await client.post(
        "/users",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": existing.email, "password": "Abcdef1!", "role": "reviewer"},
    )
    assert resp.status_code == 409


async def test_list_is_client_scoped(client, make_user):
    """An admin lists only its own client's users (SC-003)."""
    admin_a = await make_user(role="admin", client_id=101)
    await make_user(role="reviewer", client_id=101)
    await make_user(role="reviewer", client_id=202)
    token = await login_token(client, admin_a.email)
    resp = await client.get("/users", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert {u["client_id"] for u in resp.json()} == {101}


async def test_deactivate_blocks_login(client, make_user):
    """Deactivating a user prevents further authentication (FR-008)."""
    admin = await make_user(role="admin", client_id=303)
    target = await make_user(role="reviewer", client_id=303)
    token = await login_token(client, admin.email)
    resp = await client.patch(
        f"/users/{target.id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"is_active": False},
    )
    assert resp.status_code == 200
    assert (
        await client.post(
            "/auth/jwt/login", data={"username": target.email, "password": "Abcdef1!"}
        )
    ).status_code == 400


async def test_cross_tenant_patch_is_404(client, make_user):
    """An admin cannot touch another client's user; existence is not revealed (SC-003)."""
    admin_a = await make_user(role="admin", client_id=401)
    user_b = await make_user(role="reviewer", client_id=402)
    token = await login_token(client, admin_a.email)
    resp = await client.patch(
        f"/users/{user_b.id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"role": "admin"},
    )
    assert resp.status_code == 404


async def test_last_admin_cannot_be_deactivated_or_demoted(client, make_user):
    """The last active admin of a client cannot be deactivated or demoted (FR-013/SC-008)."""
    admin = await make_user(role="admin", client_id=505)
    token = await login_token(client, admin.email)
    deactivate = await client.patch(
        f"/users/{admin.id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"is_active": False},
    )
    demote = await client.patch(
        f"/users/{admin.id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"role": "reviewer"},
    )
    assert deactivate.status_code == 409
    assert demote.status_code == 409


async def test_non_admin_forbidden(client, make_user):
    """A reviewer cannot use any user-management endpoint (FR-014)."""
    reviewer = await make_user(role="reviewer")
    token = await login_token(client, reviewer.email)
    headers = {"Authorization": f"Bearer {token}"}
    assert (await client.get("/users", headers=headers)).status_code == 403
    assert (
        await client.post(
            "/users",
            headers=headers,
            json={"email": _email(), "password": "Abcdef1!", "role": "reviewer"},
        )
    ).status_code == 403
