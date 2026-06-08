"""Concurrency tests: unique-name and idempotent-item writes are race-safe (no 500s)."""

import asyncio
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
    return tenant, {"Authorization": f"Bearer {token}"}


def _payload(name):
    return {"name": name, "items": [{"item_type": "drug", "value": "atorvastatin"}]}


async def test_concurrent_create_same_name(client, make_client, make_user):
    """Firing N identical creates at once yields exactly one 201 and the rest 409 — never 500."""
    _, h = await _admin(client, make_client, make_user)
    name = f"Race-{uuid.uuid4().hex[:8]}"
    results = await asyncio.gather(
        *(client.post("/watchlists", headers=h, json=_payload(name)) for _ in range(8))
    )
    codes = sorted(r.status_code for r in results)
    assert 500 not in codes, f"a race produced a 500: {codes}"
    assert codes.count(201) == 1, f"expected exactly one create to win: {codes}"
    assert all(c in (201, 409) for c in codes), codes
    # And only one row actually exists.
    listing = (await client.get("/watchlists", headers=h)).json()
    assert sum(1 for w in listing if w["name"] == name) == 1


async def test_concurrent_duplicate_item_add(client, make_client, make_user):
    """Firing N identical item-adds at once is idempotent: one row, all 2xx — never 500."""
    _, h = await _admin(client, make_client, make_user)
    wl = (
        await client.post("/watchlists", headers=h, json=_payload(f"WL-{uuid.uuid4().hex[:8]}"))
    ).json()
    item = {"item_type": "keyword", "value": "rash"}
    results = await asyncio.gather(
        *(client.post(f"/watchlists/{wl['id']}/items", headers=h, json=item) for _ in range(8))
    )
    codes = sorted(r.status_code for r in results)
    assert 500 not in codes, f"a race produced a 500: {codes}"
    assert all(c in (200, 201) for c in codes), codes
    assert codes.count(201) <= 1, f"at most one real insert: {codes}"
    # Exactly one matching item exists in the end.
    final = (await client.get(f"/watchlists/{wl['id']}", headers=h)).json()
    assert (
        sum(1 for i in final["items"] if i["item_type"] == "keyword" and i["value"] == "rash") == 1
    )
