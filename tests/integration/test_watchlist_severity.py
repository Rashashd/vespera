"""Per-watchlist severity-threshold configuration: set, default, validate (US4, FR-007)."""

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


async def test_default_severity_is_serious(client, make_client, make_user):
    """Severity threshold defaults to serious when unset (FR-007)."""
    h = await _admin(client, make_client, make_user)
    wl = (await client.post("/watchlists", headers=h, json=_payload())).json()
    assert wl["severity_threshold"] == "serious"


async def test_set_severity(client, make_client, make_user):
    """A valid severity threshold is stored and read back (FR-007)."""
    h = await _admin(client, make_client, make_user)
    wl = (
        await client.post(
            "/watchlists", headers=h, json=_payload(severity_threshold="life-threatening")
        )
    ).json()
    assert wl["severity_threshold"] == "life-threatening"
    patched = await client.patch(
        f"/watchlists/{wl['id']}", headers=h, json={"severity_threshold": "non-serious"}
    )
    assert patched.status_code == 200 and patched.json()["severity_threshold"] == "non-serious"


async def test_invalid_severity_is_422(client, make_client, make_user):
    """An out-of-set severity threshold is rejected with 422 (FR-007)."""
    h = await _admin(client, make_client, make_user)
    resp = await client.post("/watchlists", headers=h, json=_payload(severity_threshold="fatal"))
    assert resp.status_code == 422
