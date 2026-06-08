"""Authorization & multi-tenant isolation for watchlists (SC-003, SC-007)."""

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


async def _headers(client, make_user, *, role, client_id):
    user = await make_user(role=role, client_id=client_id)
    token = await login_token(client, user.email)
    return {"Authorization": f"Bearer {token}"}


async def test_admin_can_write(client, make_client, make_user):
    """An admin can create a watchlist (FR-013)."""
    tenant = await make_client()
    h = await _headers(client, make_user, role="admin", client_id=tenant.id)
    assert (await client.post("/watchlists", headers=h, json=_payload())).status_code == 201


async def test_reviewer_reads_but_cannot_write(client, make_client, make_user):
    """A reviewer may GET watchlists but every write is 403 (FR-013)."""
    tenant = await make_client()
    admin_h = await _headers(client, make_user, role="admin", client_id=tenant.id)
    created = (await client.post("/watchlists", headers=admin_h, json=_payload())).json()

    rev_h = await _headers(client, make_user, role="reviewer", client_id=tenant.id)
    assert (await client.get("/watchlists", headers=rev_h)).status_code == 200
    assert (await client.get(f"/watchlists/{created['id']}", headers=rev_h)).status_code == 200
    assert (await client.post("/watchlists", headers=rev_h, json=_payload())).status_code == 403
    assert (
        await client.patch(f"/watchlists/{created['id']}", headers=rev_h, json={"cadence": "daily"})
    ).status_code == 403
    assert (
        await client.post(
            f"/watchlists/{created['id']}/items",
            headers=rev_h,
            json={"item_type": "keyword", "value": "x"},
        )
    ).status_code == 403


async def test_unauthenticated_is_401(client):
    """No token ⇒ 401 before any tenant check."""
    assert (await client.get("/watchlists")).status_code == 401
    assert (await client.post("/watchlists", json=_payload())).status_code == 401


async def test_cross_tenant_get_is_404(client, make_client, make_user):
    """Admin of client A cannot see client B's watchlist; existence is not revealed (SC-003)."""
    tenant_a = await make_client()
    tenant_b = await make_client()
    a_h = await _headers(client, make_user, role="admin", client_id=tenant_a.id)
    b_h = await _headers(client, make_user, role="admin", client_id=tenant_b.id)
    b_wl = (await client.post("/watchlists", headers=b_h, json=_payload())).json()

    assert (await client.get(f"/watchlists/{b_wl['id']}", headers=a_h)).status_code == 404
    assert (
        await client.patch(f"/watchlists/{b_wl['id']}", headers=a_h, json={"cadence": "daily"})
    ).status_code == 404
    # A's listing never includes B's watchlist.
    listing = await client.get("/watchlists", headers=a_h)
    assert b_wl["id"] not in {w["id"] for w in listing.json()}
