"""Per-watchlist cadence configuration: set, default, validate, sibling independence (US3)."""

import os
import uuid

import pytest

from tests.integration.conftest import login_token

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires the Compose stack (Vault + Postgres + Redis)",
)


async def _admin(client, make_client, make_user):
    tenant = await make_client()
    admin = await make_user(role="admin", client_id=tenant.id)
    token = await login_token(client, admin.email)
    return {"Authorization": f"Bearer {token}"}


def _payload(**over):
    body = {
        "name": f"WL-{uuid.uuid4().hex[:8]}",
        "items": [{"item_type": "drug", "value": "atorvastatin"}],
    }
    body.update(over)
    return body


async def test_default_cadence_is_weekly(client, make_client, make_user):
    """Cadence defaults to weekly when unset (FR-006)."""
    h = await _admin(client, make_client, make_user)
    wl = (await client.post("/watchlists", headers=h, json=_payload())).json()
    assert wl["cadence"] == "weekly"


async def test_set_cadence_and_sibling_independence(client, make_client, make_user):
    """Two watchlists hold independent cadences (FR-006)."""
    h = await _admin(client, make_client, make_user)
    a = (await client.post("/watchlists", headers=h, json=_payload(cadence="daily"))).json()
    b = (await client.post("/watchlists", headers=h, json=_payload())).json()
    assert a["cadence"] == "daily" and b["cadence"] == "weekly"
    patched = await client.patch(f"/watchlists/{b['id']}", headers=h, json={"cadence": "monthly"})
    assert patched.status_code == 200 and patched.json()["cadence"] == "monthly"
    # a unchanged
    a_again = await client.get(f"/watchlists/{a['id']}", headers=h)
    assert a_again.json()["cadence"] == "daily"


async def test_invalid_cadence_is_422(client, make_client, make_user):
    """An out-of-set cadence is rejected with 422 (FR-006)."""
    h = await _admin(client, make_client, make_user)
    resp = await client.post("/watchlists", headers=h, json=_payload(cadence="hourly"))
    assert resp.status_code == 422
