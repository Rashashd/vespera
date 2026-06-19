"""Integration (US5): audit access/export role model — manager all, admin scoped, reviewer 403."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.audit.handler import register_audit_handlers
from app.audit.models import AuditLog
from app.core.dispatcher import EventDispatcher
from app.domain.events import ReportApproved, WatchlistCreated


async def _login(auth_app, email: str, password: str = "Abcdef1!") -> AsyncClient:
    c = AsyncClient(transport=ASGITransport(app=auth_app), base_url="http://test")
    resp = await c.post("/auth/jwt/login", data={"username": email, "password": password})
    resp.raise_for_status()
    c.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
    return c


async def _seed_audit(factory, client_id: int) -> None:
    """Seed one report event (manager-only) and one watchlist event (admin-visible)."""
    d = EventDispatcher()
    register_audit_handlers(d)
    async with factory() as s:
        async with s.begin():
            await d.dispatch(
                ReportApproved(
                    actor_id=1,
                    actor_type="human",
                    client_id=client_id,
                    report_id=1,
                    report_type="batch",
                ),
                s,
            )
            await d.dispatch(
                WatchlistCreated(
                    actor_id=1, actor_type="human", client_id=client_id, watchlist_id=1, name="W"
                ),
                s,
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_export_role_scope_and_audited(
    auth_app, make_client, make_staff_user, priv_factory
) -> None:
    """Manager exports all; admin exports client/watchlist only; reviewer 403; export is audited."""
    cl = await make_client()
    await _seed_audit(priv_factory, cl.id)

    manager = await make_staff_user(role="manager")
    admin = await make_staff_user(role="admin")
    reviewer = await make_staff_user(role="reviewer")
    mgr_c = await _login(auth_app, manager.email)
    adm_c = await _login(auth_app, admin.email)
    rev_c = await _login(auth_app, reviewer.email)

    # Manager → all events for the client (report + watchlist).
    mgr = await mgr_c.get(f"/audit/export?format=json&client_id={cl.id}")
    assert mgr.status_code == 200
    mgr_types = {row["event_type"] for row in mgr.json()}
    assert "ReportApproved" in mgr_types
    assert "WatchlistCreated" in mgr_types

    # Admin → only client/watchlist-management events (report event excluded).
    adm = await adm_c.get(f"/audit/export?format=json&client_id={cl.id}")
    assert adm.status_code == 200
    adm_types = {row["event_type"] for row in adm.json()}
    assert "WatchlistCreated" in adm_types
    assert "ReportApproved" not in adm_types

    # Reviewer → denied.
    assert (await rev_c.get(f"/audit/export?format=csv&client_id={cl.id}")).status_code == 403

    # The manager export emitted an AuditExported audit row.
    async with priv_factory() as s:
        exported = (
            (
                await s.execute(
                    select(AuditLog).where(
                        AuditLog.event_type == "AuditExported", AuditLog.client_id == cl.id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(exported) >= 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_list_admin_scope(auth_app, make_client, make_staff_user, priv_factory) -> None:
    """GET /audit for an admin excludes report events (client/watchlist scope only)."""
    cl = await make_client()
    await _seed_audit(priv_factory, cl.id)
    admin = await make_staff_user(role="admin")
    adm_c = await _login(auth_app, admin.email)
    resp = await adm_c.get(f"/audit?client_id={cl.id}")
    assert resp.status_code == 200
    types = {row["event_type"] for row in resp.json()}
    assert "WatchlistCreated" in types
    assert "ReportApproved" not in types


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_csv_export_format(
    auth_app, make_client, make_staff_user, priv_factory
) -> None:
    """CSV export returns text/csv with a header row + attachment disposition."""
    cl = await make_client()
    await _seed_audit(priv_factory, cl.id)
    manager = await make_staff_user(role="manager")
    mgr_c = await _login(auth_app, manager.email)
    resp = await mgr_c.get(f"/audit/export?format=csv&client_id={cl.id}")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers.get("content-disposition", "")
    assert resp.text.splitlines()[0].startswith("id,created_at,actor_id")
