"""Integration tests: save-time MeSH validation on the spec-3 watchlist write path (T040)."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires the Compose stack (Vault + Postgres + Redis)",
)

from tests.integration.conftest import login_token  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _admin_headers(client, make_client, make_user):
    tenant = await make_client()
    admin = await make_user(role="admin", client_id=tenant.id)
    token = await login_token(client, admin.email)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# T040a: Create watchlist with valid + bogus MeSH terms
# ---------------------------------------------------------------------------


async def test_create_watchlist_mesh_validation(client, make_client, make_user):
    """Valid MeSH → valid; bogus → invalid; neither is rejected (FR-009, US4)."""
    headers = await _admin_headers(client, make_client, make_user)

    resp = await client.post(
        "/watchlists",
        json={
            "name": "MeSH-validation-test",
            "items": [
                {"item_type": "drug", "value": "warfarin"},
                {"item_type": "mesh", "value": "Warfarin"},  # valid heading
                {"item_type": "mesh", "value": "NotARealMeSHTerm_XYZ"},  # bogus
            ],
        },
        headers=headers,
    )
    assert resp.status_code == 201
    body = resp.json()

    items_by_value = {i["value"]: i for i in body["items"]}

    valid_item = items_by_value.get("Warfarin")
    assert valid_item is not None, "Valid MeSH heading must appear in response"
    assert valid_item.get("mesh_validity") == "valid"
    assert valid_item.get("mesh_canonical") is not None

    bogus_item = items_by_value.get("NotARealMeSHTerm_XYZ")
    assert bogus_item is not None, "Bogus MeSH term must appear in response (not rejected)"
    assert bogus_item.get("mesh_validity") == "invalid"
    assert bogus_item.get("mesh_canonical") is None

    drug_item = items_by_value.get("warfarin")
    assert drug_item is not None
    # Non-mesh items carry null validity (the columns are mesh-specific).
    assert drug_item.get("mesh_validity") is None


# ---------------------------------------------------------------------------
# T040b: Add item via POST /watchlists/{id}/items — same validation
# ---------------------------------------------------------------------------


async def test_add_item_mesh_validation(client, make_client, make_user):
    """Adding a valid MeSH item → validity set; adding invalid → flagged but accepted (US4)."""
    headers = await _admin_headers(client, make_client, make_user)

    # Create a watchlist with at least one drug item.
    create_resp = await client.post(
        "/watchlists",
        json={"name": "mesh-add-test", "items": [{"item_type": "drug", "value": "aspirin"}]},
        headers=headers,
    )
    assert create_resp.status_code == 201
    wl_id = create_resp.json()["id"]

    # Add a valid MeSH term (response is the full watchlist).
    resp_valid = await client.post(
        f"/watchlists/{wl_id}/items",
        json={"item_type": "mesh", "value": "Anticoagulants"},
        headers=headers,
    )
    assert resp_valid.status_code == 201
    items_by_value = {i["value"]: i for i in resp_valid.json()["items"]}
    valid_item = items_by_value.get("Anticoagulants")
    assert valid_item is not None
    assert valid_item["mesh_validity"] == "valid"
    assert valid_item["mesh_canonical"] is not None

    # Add an invalid MeSH term — still accepted (not rejected), just flagged.
    resp_invalid = await client.post(
        f"/watchlists/{wl_id}/items",
        json={"item_type": "mesh", "value": "BogusTermZZZ999"},
        headers=headers,
    )
    assert resp_invalid.status_code == 201
    items_by_value2 = {i["value"]: i for i in resp_invalid.json()["items"]}
    invalid_item = items_by_value2.get("BogusTermZZZ999")
    assert invalid_item is not None
    assert invalid_item["mesh_validity"] == "invalid"
    assert invalid_item["mesh_canonical"] is None


# ---------------------------------------------------------------------------
# T040c: Flags don't block — invalid term is still searchable
# ---------------------------------------------------------------------------


async def test_invalid_mesh_does_not_block_watchlist_creation(client, make_client, make_user):
    """A watchlist with only invalid MeSH terms is still created without error (FR-009)."""
    headers = await _admin_headers(client, make_client, make_user)

    resp = await client.post(
        "/watchlists",
        json={
            "name": "all-invalid-mesh",
            "items": [{"item_type": "mesh", "value": "AbsolutelyNotRealXYZ123"}],
        },
        headers=headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    item = body["items"][0]
    assert item["mesh_validity"] == "invalid"
