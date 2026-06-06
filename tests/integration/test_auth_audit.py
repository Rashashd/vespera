"""Audit-trail integration tests: one row per security event, correct attribution (US3)."""

import os
import uuid

import pytest
from sqlalchemy import func, select

from tests.integration.conftest import login_token

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires the Compose stack (Vault + Postgres + Redis)",
)


async def _count(auth_app, **filters):
    from app.db.models import AuditLog

    stmt = select(func.count()).select_from(AuditLog)
    for col, val in filters.items():
        stmt = stmt.where(getattr(AuditLog, col) == val)
    async with auth_app.state.session_factory() as s:
        return await s.scalar(stmt) or 0


async def test_successful_login_is_audited_with_fk(client, make_user, auth_app):
    """A successful login writes one human-attributed row with actor_user_id set (FR-012)."""
    user = await make_user()
    before = await _count(auth_app, event_type="UserLoggedIn", actor_user_id=user.id)
    await login_token(client, user.email)
    after = await _count(auth_app, event_type="UserLoggedIn", actor_user_id=user.id)
    assert after == before + 1


async def test_failed_login_unknown_email_is_system_actor(client, auth_app):
    """An unknown-email failed login is recorded as a system event (sentinel 0, NULL FK)."""
    from app.db.models import SYSTEM_ACTOR_ID, AuditLog

    email = f"{uuid.uuid4().hex}@x.com"
    await client.post("/auth/jwt/login", data={"username": email, "password": "Nope1234!"})
    async with auth_app.state.session_factory() as s:
        row = (
            await s.scalars(
                select(AuditLog)
                .where(AuditLog.event_type == "LoginFailed")
                .order_by(AuditLog.id.desc())
                .limit(1)
            )
        ).first()
    assert row is not None
    assert row.actor_type == "system"
    assert row.actor_id == SYSTEM_ACTOR_ID
    assert row.actor_user_id is None
    # No password material is ever stored in the payload (SC-005).
    assert "password" not in (row.payload or {})


async def test_user_created_is_audited(client, make_user, auth_app):
    """Admin user creation writes one UserCreated row attributed to the admin."""
    admin = await make_user(role="admin", client_id=900)
    token = await login_token(client, admin.email)
    await client.post(
        "/users",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": f"{uuid.uuid4().hex}@x.com", "password": "Abcdef1!", "role": "reviewer"},
    )
    created = await _count(auth_app, event_type="UserCreated", actor_user_id=admin.id)
    assert created == 1
