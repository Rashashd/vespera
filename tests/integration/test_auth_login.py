"""Login integration tests: token issuance, generic failures, token rejection (US1)."""

import os

import pytest

from tests.integration.conftest import login_token

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires the Compose stack (Vault + Postgres + Redis)",
)


async def test_login_success_returns_bearer_token(client, make_user):
    """Valid credentials yield a bearer access token (FR-001)."""
    user = await make_user(password="Abcdef1!")
    resp = await client.post(
        "/auth/jwt/login", data={"username": user.email, "password": "Abcdef1!"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


async def test_wrong_password_is_generic(client, make_user):
    """A wrong password is refused with a generic, non-enumerating error (FR-002)."""
    user = await make_user(password="Abcdef1!")
    bad = await client.post(
        "/auth/jwt/login", data={"username": user.email, "password": "Wrongpass1!"}
    )
    missing = await client.post(
        "/auth/jwt/login", data={"username": "nobody@x.com", "password": "Wrongpass1!"}
    )
    assert bad.status_code == 400
    assert missing.status_code == 400
    # Identical body whether or not the email exists (no enumeration).
    assert bad.json() == missing.json() == {"detail": "LOGIN_BAD_CREDENTIALS"}


async def test_deactivated_user_cannot_login(client, make_user):
    """A deactivated account cannot authenticate (FR-008)."""
    user = await make_user(password="Abcdef1!", is_active=False)
    resp = await client.post(
        "/auth/jwt/login", data={"username": user.email, "password": "Abcdef1!"}
    )
    assert resp.status_code == 400


async def test_protected_endpoint_rejects_bad_tokens(client, make_user):
    """No token, a tampered token, and a malformed token are all rejected as 401 (FR-003)."""
    user = await make_user(password="Abcdef1!")
    token = await login_token(client, user.email)

    assert (await client.post("/auth/jwt/logout")).status_code == 401
    tampered = token[:-2] + ("aa" if not token.endswith("aa") else "bb")
    assert (
        await client.post("/auth/jwt/logout", headers={"Authorization": f"Bearer {tampered}"})
    ).status_code == 401
    assert (
        await client.post("/auth/jwt/logout", headers={"Authorization": "Bearer not.a.jwt"})
    ).status_code == 401
    # The valid token works.
    assert (
        await client.post("/auth/jwt/logout", headers={"Authorization": f"Bearer {token}"})
    ).status_code == 204
