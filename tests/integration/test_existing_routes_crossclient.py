"""T020: Staff cross-client route access and client-user restriction tests (spec 4b, FR-006/FR-008).

Staff admin can manage watchlists for ANY client; staff reviewer can read ANY client's watchlists;
client-users can only access their own client's watchlists.
"""

from __future__ import annotations

import os
import uuid

import pytest

from tests.integration.conftest import login_token

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires the Compose stack (Vault + Postgres + Redis)",
)


def _wl_payload():
    return {
        "name": f"WL-{uuid.uuid4().hex[:8]}",
        "items": [{"item_type": "drug", "value": "metformin"}],
    }


# ---------------------------------------------------------------------------
# Staff admin cross-client write access (FR-006)
# ---------------------------------------------------------------------------


async def test_staff_admin_creates_watchlist_for_any_client(client, make_client, make_staff_user):
    """Staff admin can create a watchlist for a client they have no personal FK to (FR-006)."""
    tenant_a = await make_client()
    tenant_b = await make_client()
    admin = await make_staff_user(role="admin")
    token = await login_token(client, admin.email)
    h = {"Authorization": f"Bearer {token}"}

    # Admin creates a watchlist for tenant_b (not tenant_a — proves cross-client works).
    resp = await client.post(f"/clients/{tenant_b.id}/watchlists", json=_wl_payload(), headers=h)
    assert resp.status_code == 201
    assert resp.json()["client_id"] == tenant_b.id

    # Same admin can also list tenant_a's (empty) watchlists — not restricted to tenant_b.
    list_resp = await client.get(f"/clients/{tenant_a.id}/watchlists", headers=h)
    assert list_resp.status_code == 200


async def test_staff_admin_triggers_ingestion_for_any_client(client, make_client, make_staff_user):
    """Staff admin can trigger ingestion for any client's watchlist (FR-006)."""
    tenant = await make_client()
    admin = await make_staff_user(role="admin")
    token = await login_token(client, admin.email)
    h = {"Authorization": f"Bearer {token}"}

    wl = (
        await client.post(f"/clients/{tenant.id}/watchlists", json=_wl_payload(), headers=h)
    ).json()
    resp = await client.post(f"/clients/{tenant.id}/watchlists/{wl['id']}/ingest", headers=h)
    assert resp.status_code == 202


# ---------------------------------------------------------------------------
# Staff reviewer cross-client read access
# ---------------------------------------------------------------------------


async def test_staff_reviewer_reads_any_client_watchlists(client, make_client, make_staff_user):
    """Staff reviewer can list watchlists for any client (read-only cross-client access)."""
    tenant = await make_client()
    admin = await make_staff_user(role="admin")
    reviewer = await make_staff_user(role="reviewer")

    admin_token = await login_token(client, admin.email)
    admin_h = {"Authorization": f"Bearer {admin_token}"}
    rev_token = await login_token(client, reviewer.email)
    rev_h = {"Authorization": f"Bearer {rev_token}"}

    # Admin creates a watchlist.
    wl = (
        await client.post(f"/clients/{tenant.id}/watchlists", json=_wl_payload(), headers=admin_h)
    ).json()

    # Reviewer can list and get it.
    list_resp = await client.get(f"/clients/{tenant.id}/watchlists", headers=rev_h)
    assert list_resp.status_code == 200
    assert wl["id"] in {w["id"] for w in list_resp.json()}

    get_resp = await client.get(f"/clients/{tenant.id}/watchlists/{wl['id']}", headers=rev_h)
    assert get_resp.status_code == 200


async def test_staff_reviewer_cannot_write_watchlist(client, make_client, make_staff_user):
    """Staff reviewer is forbidden from creating/modifying watchlists (403, FR-013)."""
    tenant = await make_client()
    reviewer = await make_staff_user(role="reviewer")
    token = await login_token(client, reviewer.email)
    h = {"Authorization": f"Bearer {token}"}

    resp = await client.post(f"/clients/{tenant.id}/watchlists", json=_wl_payload(), headers=h)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Client-user own-client restriction on watchlist routes (SC-009)
# ---------------------------------------------------------------------------


async def test_client_user_reads_own_client_watchlists(
    client, make_client, make_staff_user, make_user
):
    """A client-user with full scope can read their own client's watchlists."""
    tenant = await make_client()
    admin = await make_staff_user(role="admin")
    client_user = await make_user(role="client_user", client_id=tenant.id)

    admin_token = await login_token(client, admin.email)
    admin_h = {"Authorization": f"Bearer {admin_token}"}
    cu_token = await login_token(client, client_user.email)
    cu_h = {"Authorization": f"Bearer {cu_token}"}

    wl = (
        await client.post(f"/clients/{tenant.id}/watchlists", json=_wl_payload(), headers=admin_h)
    ).json()

    # Client-user can list and get their own client's watchlists.
    list_resp = await client.get(f"/clients/{tenant.id}/watchlists", headers=cu_h)
    assert list_resp.status_code == 200
    assert wl["id"] in {w["id"] for w in list_resp.json()}


async def test_client_user_cannot_access_other_client_watchlists(
    client, make_client, make_staff_user, make_user
):
    """A client-user naming another client's id gets 404 (existence not revealed, SC-009)."""
    tenant_a = await make_client()
    tenant_b = await make_client()
    admin = await make_staff_user(role="admin")
    client_user_a = await make_user(role="client_user", client_id=tenant_a.id)

    admin_token = await login_token(client, admin.email)
    admin_h = {"Authorization": f"Bearer {admin_token}"}
    cu_token = await login_token(client, client_user_a.email)
    cu_h = {"Authorization": f"Bearer {cu_token}"}

    # Create a watchlist for tenant_b.
    await client.post(f"/clients/{tenant_b.id}/watchlists", json=_wl_payload(), headers=admin_h)

    # client_user_a names tenant_b → 404 (existence not leaked).
    resp = await client.get(f"/clients/{tenant_b.id}/watchlists", headers=cu_h)
    assert resp.status_code == 404


async def test_client_user_cannot_write_watchlist(client, make_client, make_user):
    """A client-user cannot create watchlists even for their own client (writes are staff-only)."""
    tenant = await make_client()
    client_user = await make_user(role="client_user", client_id=tenant.id)
    token = await login_token(client, client_user.email)
    h = {"Authorization": f"Bearer {token}"}

    resp = await client.post(f"/clients/{tenant.id}/watchlists", json=_wl_payload(), headers=h)
    assert resp.status_code == 403
