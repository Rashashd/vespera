"""Authorization & multi-tenant isolation for watchlists (agency model, spec 4b, SC-003/SC-007)."""

import os
import uuid

import pytest

from tests.integration.conftest import login_token

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires the Compose stack (Vault + Postgres + Redis)",
)


def _payload():
    return {
        "name": f"WL-{uuid.uuid4().hex[:8]}",
        "items": [{"item_type": "drug", "value": "atorvastatin"}],
    }


async def _staff_headers(client, make_staff_user, *, role):
    user = await make_staff_user(role=role)
    token = await login_token(client, user.email)
    return {"Authorization": f"Bearer {token}"}


async def test_admin_can_write(client, make_client, make_staff_user):
    """A staff admin can create a watchlist for any client (FR-013, FR-006)."""
    tenant = await make_client()
    h = await _staff_headers(client, make_staff_user, role="admin")
    assert (
        await client.post(f"/clients/{tenant.id}/watchlists", headers=h, json=_payload())
    ).status_code == 201


async def test_reviewer_reads_but_cannot_write(client, make_client, make_staff_user):
    """A staff reviewer may GET watchlists but every write is 403 (FR-013)."""
    tenant = await make_client()
    admin_h = await _staff_headers(client, make_staff_user, role="admin")
    created = (
        await client.post(f"/clients/{tenant.id}/watchlists", headers=admin_h, json=_payload())
    ).json()

    rev_h = await _staff_headers(client, make_staff_user, role="reviewer")
    assert (await client.get(f"/clients/{tenant.id}/watchlists", headers=rev_h)).status_code == 200
    assert (
        await client.get(f"/clients/{tenant.id}/watchlists/{created['id']}", headers=rev_h)
    ).status_code == 200
    assert (
        await client.post(f"/clients/{tenant.id}/watchlists", headers=rev_h, json=_payload())
    ).status_code == 403
    assert (
        await client.patch(
            f"/clients/{tenant.id}/watchlists/{created['id']}",
            headers=rev_h,
            json={"cadence": "daily"},
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/clients/{tenant.id}/watchlists/{created['id']}/items",
            headers=rev_h,
            json={"item_type": "keyword", "value": "x"},
        )
    ).status_code == 403


async def test_unauthenticated_is_401(client, make_client):
    """No token ⇒ 401 before any tenant check."""
    tenant = await make_client()
    assert (await client.get(f"/clients/{tenant.id}/watchlists")).status_code == 401
    assert (
        await client.post(f"/clients/{tenant.id}/watchlists", json=_payload())
    ).status_code == 401


async def test_wrong_client_id_in_path_is_404(client, make_client, make_staff_user):
    """Staff admin naming the wrong client for a watchlist gets 404 (SC-003)."""
    tenant_a = await make_client()
    tenant_b = await make_client()
    h = await _staff_headers(client, make_staff_user, role="admin")
    # Create watchlist under tenant_b.
    b_wl = (
        await client.post(f"/clients/{tenant_b.id}/watchlists", headers=h, json=_payload())
    ).json()

    # Naming tenant_a for tenant_b's watchlist id → 404 (watchlist not there).
    assert (
        await client.get(f"/clients/{tenant_a.id}/watchlists/{b_wl['id']}", headers=h)
    ).status_code == 404
    assert (
        await client.patch(
            f"/clients/{tenant_a.id}/watchlists/{b_wl['id']}",
            headers=h,
            json={"cadence": "daily"},
        )
    ).status_code == 404
    # Tenant A's listing never includes tenant B's watchlist.
    listing = await client.get(f"/clients/{tenant_a.id}/watchlists", headers=h)
    assert b_wl["id"] not in {w["id"] for w in listing.json()}
