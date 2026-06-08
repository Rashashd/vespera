"""Ingestion trigger authz, eligibility, one-audit-row, and incremental-run integration tests."""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import func, select

from tests.integration.conftest import login_token

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires the Compose stack (Vault + Postgres + Redis)",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _wl_name() -> str:
    return f"WL-{uuid.uuid4().hex[:8]}"


async def _audit_count(auth_app, *, action: str, client_id: int) -> int:
    from app.db.models import AuditLog

    async with auth_app.state.session_factory() as s:
        return (
            await s.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == action, AuditLog.client_id == client_id)
            )
            or 0
        )


async def _create_watchlist(client, headers, *, name=None, items=None) -> dict:
    payload = {
        "name": name or _wl_name(),
        "items": items
        or [
            {"item_type": "drug", "value": "warfarin"},
            {"item_type": "keyword", "value": "hepatotoxicity"},
        ],
    }
    resp = await client.post("/watchlists", json=payload, headers=headers)
    resp.raise_for_status()
    return resp.json()


async def _make_admin(client, make_client, make_user) -> tuple:
    tenant = await make_client()
    admin = await make_user(role="admin", client_id=tenant.id)
    token = await login_token(client, admin.email)
    headers = {"Authorization": f"Bearer {token}"}
    return tenant, admin, headers


# ---------------------------------------------------------------------------
# T016: Trigger authz + eligibility tests
# ---------------------------------------------------------------------------


async def test_trigger_admin_accepted(client, make_client, make_user, auth_app):
    """Admin trigger on an active, non-empty watchlist → 202 + run_id in body (SC-001, US1-1)."""
    tenant, admin, headers = await _make_admin(client, make_client, make_user)
    wl = await _create_watchlist(client, headers)

    resp = await client.post(f"/watchlists/{wl['id']}/ingest", headers=headers)
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "running"
    assert body["watchlist_id"] == wl["id"]
    assert "id" in body


async def test_trigger_reviewer_forbidden(client, make_client, make_user, auth_app):
    """Reviewer may not trigger — always 403 (SC-005, US1-4)."""
    tenant, admin, admin_headers = await _make_admin(client, make_client, make_user)
    wl = await _create_watchlist(client, admin_headers)

    reviewer = await make_user(role="reviewer", client_id=tenant.id)
    rev_token = await login_token(client, reviewer.email)
    rev_headers = {"Authorization": f"Bearer {rev_token}"}

    resp = await client.post(f"/watchlists/{wl['id']}/ingest", headers=rev_headers)
    assert resp.status_code == 403


async def test_trigger_cross_tenant_not_found(client, make_client, make_user, auth_app):
    """Admin cannot trigger another tenant's watchlist — 404, no reveal (FR-001, US1-3)."""
    tenant_a, _, headers_a = await _make_admin(client, make_client, make_user)
    tenant_b, _, headers_b = await _make_admin(client, make_client, make_user)
    wl_b = await _create_watchlist(client, headers_b)

    resp = await client.post(f"/watchlists/{wl_b['id']}/ingest", headers=headers_a)
    assert resp.status_code == 404


async def test_trigger_inactive_watchlist_rejected(client, make_client, make_user, auth_app):
    """Inactive watchlist → 400 (FR-001, US1-5)."""
    tenant, admin, headers = await _make_admin(client, make_client, make_user)
    wl = await _create_watchlist(client, headers)
    # Deactivate it.
    await client.patch(f"/watchlists/{wl['id']}", json={"is_active": False}, headers=headers)

    resp = await client.post(f"/watchlists/{wl['id']}/ingest", headers=headers)
    assert resp.status_code == 400


async def test_trigger_missing_watchlist_not_found(client, make_client, make_user, auth_app):
    """Non-existent watchlist → 404 (FR-001)."""
    _, _, headers = await _make_admin(client, make_client, make_user)
    resp = await client.post("/watchlists/999999/ingest", headers=headers)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# T049: One audit row per trigger (SC-008, US5-4)
# ---------------------------------------------------------------------------


async def test_trigger_produces_one_audit_row(client, make_client, make_user, auth_app):
    """Each trigger writes exactly one IngestionRunTriggered audit log row (SC-008)."""
    tenant, admin, headers = await _make_admin(client, make_client, make_user)
    wl = await _create_watchlist(client, headers)
    before = await _audit_count(auth_app, action="IngestionRunTriggered", client_id=tenant.id)

    await client.post(f"/watchlists/{wl['id']}/ingest", headers=headers)
    after = await _audit_count(auth_app, action="IngestionRunTriggered", client_id=tenant.id)
    assert after == before + 1

    # Second trigger also writes exactly one more row.
    await client.post(f"/watchlists/{wl['id']}/ingest", headers=headers)
    assert (
        await _audit_count(auth_app, action="IngestionRunTriggered", client_id=tenant.id)
        == before + 2
    )
