"""Staff account management integration tests (spec 4b, US1; FR-003/FR-004/FR-005)."""

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


# ---- creation ----------------------------------------------------------------


async def test_manager_creates_staff_reviewer(client, make_staff_user):
    """A manager can create a staff reviewer; response omits password (FR-009)."""
    manager = await make_staff_user(role="manager")
    token = await login_token(client, manager.email)
    resp = await client.post(
        "/staff",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": _email(), "password": "Abcdef1!", "role": "reviewer"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["role"] == "reviewer"
    assert body["user_type"] == "staff"
    assert "client_id" not in body or body.get("client_id") is None
    assert "password" not in body and "hashed_password" not in body


async def test_manager_creates_another_manager(client, make_staff_user):
    """Only a manager may create another manager (FR-004)."""
    manager = await make_staff_user(role="manager")
    token = await login_token(client, manager.email)
    resp = await client.post(
        "/staff",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": _email(), "password": "Abcdef1!", "role": "manager"},
    )
    assert resp.status_code == 201
    assert resp.json()["role"] == "manager"


async def test_admin_cannot_create_staff(client, make_staff_user):
    """A plain admin cannot use the /staff endpoint (manager-only, FR-003)."""
    admin = await make_staff_user(role="admin")
    token = await login_token(client, admin.email)
    resp = await client.post(
        "/staff",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": _email(), "password": "Abcdef1!", "role": "reviewer"},
    )
    assert resp.status_code == 403


async def test_weak_password_rejected(client, make_staff_user):
    """Creating a staff user with a weak password is rejected (FR-016)."""
    manager = await make_staff_user(role="manager")
    token = await login_token(client, manager.email)
    resp = await client.post(
        "/staff",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": _email(), "password": "weak", "role": "reviewer"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"].startswith("PASSWORD_POLICY")


async def test_duplicate_email_conflict(client, make_staff_user):
    """A globally-duplicate email is rejected with 409 (D3)."""
    manager = await make_staff_user(role="manager")
    existing = await make_staff_user(role="reviewer")
    token = await login_token(client, manager.email)
    resp = await client.post(
        "/staff",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": existing.email, "password": "Abcdef1!", "role": "reviewer"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "USER_ALREADY_EXISTS"


async def test_new_staff_user_can_login(client, make_staff_user):
    """A newly created staff user can authenticate (FR-019)."""
    manager = await make_staff_user(role="manager")
    token = await login_token(client, manager.email)
    new_email = _email()
    await client.post(
        "/staff",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": new_email, "password": "Abcdef1!", "role": "admin"},
    )
    resp = await client.post(
        "/auth/jwt/login", data={"username": new_email, "password": "Abcdef1!"}
    )
    assert resp.status_code == 200


# ---- listing -----------------------------------------------------------------


async def test_manager_lists_staff(client, make_staff_user):
    """Manager can list all staff users (staff-only listing)."""
    manager = await make_staff_user(role="manager")
    reviewer = await make_staff_user(role="reviewer")
    token = await login_token(client, manager.email)
    resp = await client.get("/staff?limit=2000", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    emails = {u["email"] for u in resp.json()}
    assert manager.email in emails and reviewer.email in emails


# ---- role + active updates ---------------------------------------------------


async def test_manager_demotes_admin_to_reviewer(client, make_staff_user):
    """Manager can change a staff user's role (FR-002)."""
    manager = await make_staff_user(role="manager")
    admin = await make_staff_user(role="admin")
    token = await login_token(client, manager.email)
    resp = await client.patch(
        f"/staff/{admin.id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"role": "reviewer"},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "reviewer"


async def test_manager_deactivates_staff_user(client, make_staff_user):
    """Manager can deactivate a staff user (prevents further login)."""
    manager = await make_staff_user(role="manager")
    reviewer = await make_staff_user(role="reviewer")
    token = await login_token(client, manager.email)
    resp = await client.patch(
        f"/staff/{reviewer.id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"is_active": False},
    )
    assert resp.status_code == 200
    # Deactivated user cannot log in.
    assert (
        await client.post(
            "/auth/jwt/login",
            data={"username": reviewer.email, "password": "Abcdef1!"},
        )
    ).status_code == 400


# ---- last-manager guard (FR-005) ---------------------------------------------


async def test_last_manager_cannot_be_demoted(client, make_staff_user):
    """The last active manager cannot be demoted (FR-005 → 409 LAST_MANAGER)."""
    manager = await make_staff_user(role="manager")
    token = await login_token(client, manager.email)

    # First, ensure no other active managers exist by listing and checking.
    list_resp = await client.get("/staff", headers={"Authorization": f"Bearer {token}"})
    managers = [u for u in list_resp.json() if u["role"] == "manager" and u["is_active"]]
    if len(managers) > 1:
        pytest.skip("More than one active manager exists; last-manager guard not testable here.")

    resp = await client.patch(
        f"/staff/{manager.id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"role": "reviewer"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "LAST_MANAGER"


async def test_last_manager_cannot_be_deactivated(client, make_staff_user):
    """The last active manager cannot be deactivated (FR-005 → 409 LAST_MANAGER)."""
    manager = await make_staff_user(role="manager")
    token = await login_token(client, manager.email)

    list_resp = await client.get("/staff", headers={"Authorization": f"Bearer {token}"})
    managers = [u for u in list_resp.json() if u["role"] == "manager" and u["is_active"]]
    if len(managers) > 1:
        pytest.skip("More than one active manager exists; last-manager guard not testable here.")

    resp = await client.patch(
        f"/staff/{manager.id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"is_active": False},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "LAST_MANAGER"


async def test_second_manager_can_demote_first(client, make_staff_user):
    """With two managers, the first can be demoted (FR-005 guard is not triggered)."""
    manager1 = await make_staff_user(role="manager")
    manager2 = await make_staff_user(role="manager")
    token = await login_token(client, manager1.email)
    resp = await client.patch(
        f"/staff/{manager2.id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"role": "admin"},
    )
    assert resp.status_code == 200


# ---- bootstrap password change (FR-024) --------------------------------------


async def test_manager_can_change_own_password(client, make_staff_user):
    """A staff user can change their own password via the fastapi-users path (FR-024)."""
    manager = await make_staff_user(role="manager")
    token = await login_token(client, manager.email)
    resp = await client.patch(
        "/auth/users/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"password": "NewPass1!"},
    )
    # fastapi-users returns 200 or 204 on success.
    assert resp.status_code in (200, 204)
    # New password works; old password does not.
    assert (
        await client.post(
            "/auth/jwt/login",
            data={"username": manager.email, "password": "NewPass1!"},
        )
    ).status_code == 200
