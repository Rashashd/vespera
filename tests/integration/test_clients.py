"""Client record integration tests: /clients/me read+rename, uniqueness, suspend, audit (US1)."""

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


async def test_get_my_client(client, make_client, make_user):
    """An authenticated user reads its own client (FR-013)."""
    tenant = await make_client(name=f"Acme {uuid.uuid4().hex[:6]}")
    admin = await make_user(role="admin", client_id=tenant.id)
    token = await login_token(client, admin.email)
    resp = await client.get("/clients/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == tenant.id and body["name"] == tenant.name
    assert body["status"] == "active"


async def test_rename_my_client_is_audited(client, make_client, make_user, auth_app):
    """An admin renames its client; exactly one ClientUpdated row is written (SC-008)."""
    tenant = await make_client()
    admin = await make_user(role="admin", client_id=tenant.id)
    token = await login_token(client, admin.email)
    new_name = f"Renamed {uuid.uuid4().hex[:8]}"
    resp = await client.patch(
        "/clients/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": new_name},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == new_name
    assert await _audit_count(auth_app, event_type="ClientUpdated", client_id=tenant.id) == 1


async def test_rename_noop_writes_no_audit(client, make_client, make_user, auth_app):
    """Renaming to the current name is a no-op and writes zero audit rows (SC-008)."""
    tenant = await make_client()
    admin = await make_user(role="admin", client_id=tenant.id)
    token = await login_token(client, admin.email)
    resp = await client.patch(
        "/clients/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": tenant.name},
    )
    assert resp.status_code == 200
    assert await _audit_count(auth_app, event_type="ClientUpdated", client_id=tenant.id) == 0


async def test_duplicate_name_is_conflict(client, make_client, make_user):
    """Renaming to another client's name (case-insensitive) is a 409 (FR-001)."""
    other = await make_client(name=f"Taken {uuid.uuid4().hex[:6]}")
    tenant = await make_client()
    admin = await make_user(role="admin", client_id=tenant.id)
    token = await login_token(client, admin.email)
    resp = await client.patch(
        "/clients/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": other.name.upper()},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "CLIENT_NAME_TAKEN"


async def test_reviewer_cannot_rename(client, make_client, make_user):
    """A reviewer may read but not rename the client (FR-013)."""
    tenant = await make_client()
    reviewer = await make_user(role="reviewer", client_id=tenant.id)
    token = await login_token(client, reviewer.email)
    assert (
        await client.get("/clients/me", headers={"Authorization": f"Bearer {token}"})
    ).status_code == 200
    resp = await client.patch(
        "/clients/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Nope"},
    )
    assert resp.status_code == 403


async def test_suspend_via_script_is_audited(make_client, auth_app):
    """The operator script suspends a client and records one ClientSuspended row."""
    from app.clients.enums import ClientStatus
    from app.clients.models import Client
    from scripts import seed_client

    tenant = await make_client()
    await seed_client._set_status(tenant.id, ClientStatus.SUSPENDED)

    async with auth_app.state.session_factory() as s:
        refreshed = await s.get(Client, tenant.id)
    assert refreshed.status == "suspended"
    assert await _audit_count(auth_app, event_type="ClientSuspended", client_id=tenant.id) == 1


async def test_create_via_script_is_audited(auth_app):
    """The operator script creates an active client and records one ClientCreated row."""
    from sqlalchemy import delete

    from app.clients.models import Client
    from app.db.models import AuditLog
    from scripts import seed_client

    name = f"Scripted {uuid.uuid4().hex[:8]}"
    await seed_client._create(name)

    async with auth_app.state.session_factory() as s:
        created = await s.scalar(select(Client).where(func.lower(Client.name) == name.lower()))
    assert created is not None and created.status == "active"
    assert await _audit_count(auth_app, event_type="ClientCreated", client_id=created.id) == 1

    # Clean up the script-created rows (no fixture tracks them).
    async with auth_app.state.session_factory() as s:
        async with s.begin():
            await s.execute(delete(AuditLog).where(AuditLog.client_id == created.id))
            await s.execute(delete(Client).where(Client.id == created.id))


async def test_unauthenticated_is_401(client):
    """No token ⇒ 401 before any tenant resolution."""
    assert (await client.get("/clients/me")).status_code == 401
