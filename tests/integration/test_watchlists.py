"""Watchlist CRUD + item integration tests: lifecycle, idempotency, soft-delete, audit (US2)."""

import os
import uuid

import pytest
from sqlalchemy import func, select

from tests.integration.conftest import login_token

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires the Compose stack (Vault + Postgres + Redis)",
)


async def _audit_count(auth_app, **filters) -> int:
    from app.db.models import AuditLog

    stmt = select(func.count()).select_from(AuditLog)
    for col, val in filters.items():
        stmt = stmt.where(getattr(AuditLog, col) == val)
    async with auth_app.state.session_factory() as s:
        return await s.scalar(stmt) or 0


async def _admin(client, make_client, make_user):
    tenant = await make_client()
    admin = await make_user(role="admin", client_id=tenant.id)
    token = await login_token(client, admin.email)
    return tenant, {"Authorization": f"Bearer {token}"}


def _name() -> str:
    return f"WL-{uuid.uuid4().hex[:8]}"


def _payload(name=None, **over):
    body = {
        "name": name or _name(),
        "items": [
            {"item_type": "drug", "value": "atorvastatin"},
            {"item_type": "mesh", "value": "Myocardial Infarction"},
        ],
    }
    body.update(over)
    return body


async def test_create_with_items(client, make_client, make_user, auth_app):
    """Creating a watchlist with ≥1 item returns 201 with items and one audit row."""
    tenant, h = await _admin(client, make_client, make_user)
    resp = await client.post("/watchlists", headers=h, json=_payload())
    assert resp.status_code == 201
    body = resp.json()
    assert body["client_id"] == tenant.id
    assert {i["item_type"] for i in body["items"]} == {"drug", "mesh"}
    assert body["cadence"] == "weekly" and body["severity_threshold"] == "serious"
    assert body["budget_status"] == "ok"
    assert await _audit_count(auth_app, event_type="WatchlistCreated", client_id=tenant.id) == 1


async def test_create_empty_is_400(client, make_client, make_user):
    """An empty items list is rejected with 400 WATCHLIST_EMPTY (FR-016)."""
    _, h = await _admin(client, make_client, make_user)
    resp = await client.post("/watchlists", headers=h, json=_payload(items=[]))
    assert resp.status_code == 400
    assert resp.json()["detail"] == "WATCHLIST_EMPTY"


async def test_payload_dedup(client, make_client, make_user):
    """Duplicate items within the create payload are de-duplicated (FR-005)."""
    _, h = await _admin(client, make_client, make_user)
    resp = await client.post(
        "/watchlists",
        headers=h,
        json=_payload(
            items=[
                {"item_type": "drug", "value": "Aspirin"},
                {"item_type": "drug", "value": "aspirin"},
            ]
        ),
    )
    assert resp.status_code == 201
    assert len(resp.json()["items"]) == 1


async def test_two_names_then_duplicate_conflict(client, make_client, make_user):
    """Two distinct names succeed; reusing a name in the same client is a 409."""
    _, h = await _admin(client, make_client, make_user)
    n1, n2 = _name(), _name()
    assert (await client.post("/watchlists", headers=h, json=_payload(n1))).status_code == 201
    assert (await client.post("/watchlists", headers=h, json=_payload(n2))).status_code == 201
    dup = await client.post("/watchlists", headers=h, json=_payload(n1.upper()))
    assert dup.status_code == 409
    assert dup.json()["detail"] == "WATCHLIST_NAME_TAKEN"


async def test_list_and_get(client, make_client, make_user):
    """List returns the client's active watchlists; get returns one by id."""
    _, h = await _admin(client, make_client, make_user)
    created = (await client.post("/watchlists", headers=h, json=_payload())).json()
    listing = await client.get("/watchlists", headers=h)
    assert listing.status_code == 200
    assert created["id"] in {w["id"] for w in listing.json()}
    one = await client.get(f"/watchlists/{created['id']}", headers=h)
    assert one.status_code == 200 and one.json()["id"] == created["id"]


async def test_rename(client, make_client, make_user, auth_app):
    """Renaming a watchlist updates the name and writes one WatchlistUpdated row."""
    tenant, h = await _admin(client, make_client, make_user)
    wl = (await client.post("/watchlists", headers=h, json=_payload())).json()
    new = _name()
    resp = await client.patch(f"/watchlists/{wl['id']}", headers=h, json={"name": new})
    assert resp.status_code == 200 and resp.json()["name"] == new
    assert await _audit_count(auth_app, event_type="WatchlistUpdated", client_id=tenant.id) == 1


async def test_rename_to_sibling_name_is_conflict(client, make_client, make_user):
    """Renaming a watchlist onto a sibling's name (case-insensitive) is a 409 (FR-003)."""
    _, h = await _admin(client, make_client, make_user)
    a = (await client.post("/watchlists", headers=h, json=_payload())).json()
    b = (await client.post("/watchlists", headers=h, json=_payload())).json()
    resp = await client.patch(f"/watchlists/{b['id']}", headers=h, json={"name": a["name"].upper()})
    assert resp.status_code == 409
    assert resp.json()["detail"] == "WATCHLIST_NAME_TAKEN"


async def test_reactivate(client, make_client, make_user):
    """A deactivated watchlist that still has items can be reactivated (FR-017)."""
    _, h = await _admin(client, make_client, make_user)
    wl = (await client.post("/watchlists", headers=h, json=_payload())).json()
    await client.patch(f"/watchlists/{wl['id']}", headers=h, json={"is_active": False})
    resp = await client.patch(f"/watchlists/{wl['id']}", headers=h, json={"is_active": True})
    assert resp.status_code == 200 and resp.json()["is_active"] is True


async def test_deactivate_soft_delete(client, make_client, make_user, auth_app):
    """Deactivation soft-deletes: hidden from default list, visible with include_inactive."""
    tenant, h = await _admin(client, make_client, make_user)
    wl = (await client.post("/watchlists", headers=h, json=_payload())).json()
    resp = await client.patch(f"/watchlists/{wl['id']}", headers=h, json={"is_active": False})
    assert resp.status_code == 200 and resp.json()["is_active"] is False
    default = await client.get("/watchlists", headers=h)
    assert wl["id"] not in {w["id"] for w in default.json()}
    with_inactive = await client.get("/watchlists?include_inactive=true", headers=h)
    assert wl["id"] in {w["id"] for w in with_inactive.json()}
    assert await _audit_count(auth_app, event_type="WatchlistDeactivated", client_id=tenant.id) == 1


async def test_idempotent_item_add(client, make_client, make_user, auth_app):
    """Adding an existing item is a 200 no-op (count unchanged) with no audit row (FR-005)."""
    tenant, h = await _admin(client, make_client, make_user)
    wl = (await client.post("/watchlists", headers=h, json=_payload())).json()
    before = await _audit_count(auth_app, event_type="WatchlistItemAdded", client_id=tenant.id)
    new = await client.post(
        f"/watchlists/{wl['id']}/items", headers=h, json={"item_type": "keyword", "value": "rash"}
    )
    assert new.status_code == 201
    dup = await client.post(
        f"/watchlists/{wl['id']}/items", headers=h, json={"item_type": "keyword", "value": "RASH"}
    )
    assert dup.status_code == 200
    assert len(dup.json()["items"]) == len(new.json()["items"])
    after = await _audit_count(auth_app, event_type="WatchlistItemAdded", client_id=tenant.id)
    assert after == before + 1  # only the real add audited, not the no-op


async def test_remove_absent_item_graceful(client, make_client, make_user):
    """Removing an item that isn't there is a graceful 204 no-op (FR-005)."""
    _, h = await _admin(client, make_client, make_user)
    wl = (await client.post("/watchlists", headers=h, json=_payload())).json()
    resp = await client.delete(f"/watchlists/{wl['id']}/items/99999999", headers=h)
    assert resp.status_code == 204


async def test_remove_to_empty_is_400(client, make_client, make_user):
    """Removing the last item of an active watchlist is refused with 400 (FR-016)."""
    _, h = await _admin(client, make_client, make_user)
    wl = (
        await client.post(
            "/watchlists",
            headers=h,
            json=_payload(items=[{"item_type": "drug", "value": "solo"}]),
        )
    ).json()
    only_item = wl["items"][0]["id"]
    resp = await client.delete(f"/watchlists/{wl['id']}/items/{only_item}", headers=h)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "WATCHLIST_EMPTY"


async def test_remove_item_audited(client, make_client, make_user, auth_app):
    """Removing a non-last item succeeds (204) and writes one WatchlistItemRemoved row."""
    tenant, h = await _admin(client, make_client, make_user)
    wl = (await client.post("/watchlists", headers=h, json=_payload())).json()
    target = wl["items"][0]["id"]
    resp = await client.delete(f"/watchlists/{wl['id']}/items/{target}", headers=h)
    assert resp.status_code == 204
    assert await _audit_count(auth_app, event_type="WatchlistItemRemoved", client_id=tenant.id) == 1
