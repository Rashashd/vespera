"""Audit-log append-only and event attribution tests (spec 4b, US5; FR-013/FR-021)."""

import os
import uuid

import pytest

from tests.integration.conftest import login_token

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires the Compose stack (Vault + Postgres + Redis)",
)


async def _count_audit(factory, event_type: str, client_id: int | None = None) -> int:
    """Count audit rows of a given event_type, optionally filtered by client_id."""
    from sqlalchemy import func, select

    from app.db.models import AuditLog

    async with factory() as s:
        stmt = select(func.count()).select_from(AuditLog).where(AuditLog.event_type == event_type)
        if client_id is not None:
            stmt = stmt.where(AuditLog.client_id == client_id)
        return await s.scalar(stmt) or 0


async def test_client_created_audit(client, make_staff_user, make_client, auth_app):
    """POST /clients creates exactly one ClientCreated audit entry (FR-021)."""
    manager = await make_staff_user(role="manager")
    token = await login_token(client, manager.email)
    name = f"AuditLC-{uuid.uuid4().hex[:8]}"

    resp = await client.post(
        "/clients",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": name},
    )
    assert resp.status_code == 201
    created_id = resp.json()["id"]
    after = await _count_audit(
        auth_app.state.session_factory, "ClientCreated", client_id=created_id
    )
    assert after == 1

    # Cleanup
    from sqlalchemy import delete

    from app.clients.models import Client
    from app.db.models import AuditLog

    factory = auth_app.state.session_factory
    async with factory() as s:
        async with s.begin():
            await s.execute(delete(AuditLog).where(AuditLog.client_id == created_id))
            await s.execute(delete(Client).where(Client.id == created_id))


async def test_client_suspended_audit(client, make_staff_user, make_client, auth_app):
    """POST /clients/{id}/suspend creates exactly one ClientSuspended audit entry."""
    manager = await make_staff_user(role="manager")
    target = await make_client()
    token = await login_token(client, manager.email)

    before = await _count_audit(
        auth_app.state.session_factory, "ClientSuspended", client_id=target.id
    )
    await client.post(f"/clients/{target.id}/suspend", headers={"Authorization": f"Bearer {token}"})
    after = await _count_audit(
        auth_app.state.session_factory, "ClientSuspended", client_id=target.id
    )
    assert after == before + 1


async def test_staff_created_audit(client, make_staff_user, auth_app):
    """POST /staff creates exactly one UserCreated audit entry for the new user."""
    from sqlalchemy import func, select

    from app.db.models import AuditLog

    manager = await make_staff_user(role="manager")
    token = await login_token(client, manager.email)

    factory = auth_app.state.session_factory
    resp = await client.post(
        "/staff",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": f"{uuid.uuid4().hex}@x.com", "password": "Abcdef1!", "role": "reviewer"},
    )
    assert resp.status_code == 201
    new_user_id = resp.json()["id"]

    async with factory() as s:
        count = await s.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.event_type == "UserCreated",
                AuditLog.payload["target_user_id"].as_integer() == new_user_id,
            )
        )
    assert count == 1


async def test_no_audit_delete_endpoint(client, make_staff_user):
    """There is no DELETE /audit endpoint — audit log is append-only (FR-013)."""
    admin = await make_staff_user(role="admin")
    token = await login_token(client, admin.email)
    resp = await client.delete("/audit/1", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 404


async def test_audit_records_target_client_id(client, make_staff_user, make_client, auth_app):
    """Staff events record the target client_id in audit_log, not the actor's (NULL) (D11)."""
    from sqlalchemy import select

    from app.db.models import AuditLog

    manager = await make_staff_user(role="manager")
    target = await make_client()
    token = await login_token(client, manager.email)

    await client.post(f"/clients/{target.id}/suspend", headers={"Authorization": f"Bearer {token}"})

    factory = auth_app.state.session_factory
    async with factory() as s:
        entry = await s.scalar(
            select(AuditLog)
            .where(
                AuditLog.event_type == "ClientSuspended",
                AuditLog.client_id == target.id,
            )
            .order_by(AuditLog.id.desc())
        )
    assert entry is not None
    assert entry.client_id == target.id
    assert entry.actor_id == manager.id
