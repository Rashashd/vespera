"""Integration tests for the staff audit-log viewer endpoint (GET /audit)."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog


async def _seed_entries(session: AsyncSession, client_id: int) -> None:
    """Insert one login (excluded) and two change events (surfaced)."""
    session.add_all(
        [
            AuditLog(
                actor_id=1,
                actor_type="human",
                actor_user_id=1,
                action="UserLoggedIn",
                target="user:1",
                event_type="UserLoggedIn",
                client_id=client_id,
                payload={},
            ),
            AuditLog(
                actor_id=1,
                actor_type="human",
                actor_user_id=1,
                action="ReportApproved",
                target="report:99",
                event_type="ReportApproved",
                client_id=client_id,
                payload={"report_id": 99},
            ),
            AuditLog(
                actor_id=1,
                actor_type="human",
                actor_user_id=1,
                action="ClientUpdated",
                target=f"client:{client_id}",
                event_type="ClientUpdated",
                client_id=client_id,
                payload={},
            ),
        ]
    )
    await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_excludes_login_events(
    authed_manager_client: AsyncClient,
    make_client,
    async_session: AsyncSession,
) -> None:
    """The viewer surfaces changes/outcomes but never login/access noise.

    Uses a manager: spec-13 FR-018 restricts admins to client/watchlist events, so full
    cross-category visibility (incl. report events) is a manager capability.
    """
    cl = await make_client()
    await _seed_entries(async_session, cl.id)

    resp = await authed_manager_client.get(f"/audit?client_id={cl.id}")
    assert resp.status_code == 200
    types = {e["event_type"] for e in resp.json()}
    assert "ReportApproved" in types
    assert "ClientUpdated" in types
    assert "UserLoggedIn" not in types


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_category_reports_filters(
    authed_manager_client: AsyncClient,
    make_client,
    async_session: AsyncSession,
) -> None:
    """category=reports returns only report-class events (manager sees all categories)."""
    cl = await make_client()
    await _seed_entries(async_session, cl.id)

    resp = await authed_manager_client.get(f"/audit?client_id={cl.id}&category=reports")
    assert resp.status_code == 200
    types = {e["event_type"] for e in resp.json()}
    assert types == {"ReportApproved"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_reviewer_denied(authed_reviewer_client: AsyncClient) -> None:
    """Reviewers cannot read the audit log (require_admin guard)."""
    resp = await authed_reviewer_client.get("/audit")
    assert resp.status_code in (403, 404)
