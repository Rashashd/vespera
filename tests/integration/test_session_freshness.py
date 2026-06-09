"""Session freshness: demotion/deactivation/suspension effective next request (spec 4b, US5)."""

import os
import uuid

import pytest

from tests.integration.conftest import login_token

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires the Compose stack (Vault + Postgres + Redis)",
)


async def test_deactivation_blocks_access_immediately(client, make_staff_user, make_client):
    """Deactivating a staff user blocks their token on the very next request (FR-019)."""
    admin = await make_staff_user(role="admin")
    manager = await make_staff_user(role="manager")
    target = await make_client()
    admin_token = await login_token(client, admin.email)
    manager_token = await login_token(client, manager.email)

    # Admin can access a require_staff route
    resp = await client.get(
        f"/clients/{target.id}", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 200

    # Manager deactivates admin
    await client.patch(
        f"/staff/{admin.id}",
        headers={"Authorization": f"Bearer {manager_token}"},
        json={"is_active": False},
    )

    # Old token, same request → 401 NOT_AUTHENTICATED
    resp = await client.get(
        f"/clients/{target.id}", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 401


async def test_role_demotion_effective_next_request(client, make_staff_user, make_client):
    """Demoting admin→reviewer blocks manager-only access on the next request (FR-019)."""
    admin = await make_staff_user(role="admin")
    manager = await make_staff_user(role="manager")
    target = await make_client()
    admin_token = await login_token(client, admin.email)
    manager_token = await login_token(client, manager.email)

    # Admin can access a require_admin route (report-emails)
    resp = await client.patch(
        f"/clients/{target.id}/report-emails",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"report_email_regular": "pre@pharma.com"},
    )
    assert resp.status_code == 200

    # Manager demotes admin → reviewer
    await client.patch(
        f"/staff/{admin.id}",
        headers={"Authorization": f"Bearer {manager_token}"},
        json={"role": "reviewer"},
    )

    # Same old token, same require_admin route → 403 (reviewer can't)
    resp = await client.patch(
        f"/clients/{target.id}/report-emails",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"report_email_regular": "post@pharma.com"},
    )
    assert resp.status_code == 403


async def test_client_suspension_blocks_client_user_next_request(
    client, make_staff_user, make_client, auth_app
):
    """Suspending a client blocks its users via the freshness check on the next request."""
    from app.auth.backend import password_helper
    from app.auth.models import User

    target = await make_client()
    manager = await make_staff_user(role="manager")
    manager_token = await login_token(client, manager.email)

    pw = "Abcdef1!"
    email = f"{uuid.uuid4().hex}@x.com"
    factory = auth_app.state.session_factory
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

    # Before suspension: client-user gets 403 FORBIDDEN (wrong user_type, not CLIENT_SUSPENDED)
    resp = await client.get(f"/clients/{target.id}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "FORBIDDEN"

    # Manager suspends the client
    await client.post(
        f"/clients/{target.id}/suspend",
        headers={"Authorization": f"Bearer {manager_token}"},
    )

    # Same token, same route → CLIENT_SUSPENDED (freshness check fires before role check)
    resp = await client.get(f"/clients/{target.id}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "CLIENT_SUSPENDED"
