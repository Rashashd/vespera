"""US3 RLS isolation (needs live Postgres + both roles): default-deny, scope, staff, write-reject.

Seeds via the privileged role (bypasses RLS, like migrations/seed), then asserts the
least-privilege pantera_app role enforces tenant isolation under per-transaction context.
Also asserts FR-020: a staff cross-client action under staff context still records an audit row
naming the target client (RLS staff-context must not break attribution; analyze G1).
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError

from app.db.base import create_engine, create_session_factory
from app.db.rls import set_rls_context

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"), reason="requires live Postgres + pantera_app role"
)


@pytest_asyncio.fixture
async def app_factory(auth_app):
    """Least-privilege (pantera_app) session factory — RLS-enforced runtime role."""
    engine = create_engine(auth_app.state.settings.app_database_url)
    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def two_clients(priv_factory):
    """Seed two clients each with one watchlist (privileged role); clean up after."""
    from app.clients.models import Client, Watchlist

    async with priv_factory() as s:
        async with s.begin():
            ca = Client(name=f"RLS-A-{uuid.uuid4().hex[:8]}", status="active")
            cb = Client(name=f"RLS-B-{uuid.uuid4().hex[:8]}", status="active")
            s.add_all([ca, cb])
            await s.flush()
            wa = Watchlist(
                client_id=ca.id,
                name="wl-a",
                is_active=True,
                cadence="weekly",
                severity_threshold="serious",
            )
            wb = Watchlist(
                client_id=cb.id,
                name="wl-b",
                is_active=True,
                cadence="weekly",
                severity_threshold="serious",
            )
            s.add_all([wa, wb])
            await s.flush()
            ids = {"a": ca.id, "b": cb.id, "wa": wa.id, "wb": wb.id}

    yield ids

    async with priv_factory() as s:
        async with s.begin():
            await s.execute(delete(Watchlist).where(Watchlist.client_id.in_([ids["a"], ids["b"]])))
            await s.execute(delete(Client).where(Client.id.in_([ids["a"], ids["b"]])))


async def _visible_watchlist_clients(session, ids) -> list[int]:
    from app.clients.models import Watchlist

    return list(
        (
            await session.execute(
                select(Watchlist.client_id)
                .where(Watchlist.id.in_([ids["wa"], ids["wb"]]))
                .order_by(Watchlist.client_id)
            )
        )
        .scalars()
        .all()
    )


async def test_default_deny_without_context(app_factory, two_clients):
    async with app_factory() as s:
        async with s.begin():
            assert await _visible_watchlist_clients(s, two_clients) == []  # default-deny


async def test_client_scope_sees_only_own(app_factory, two_clients):
    async with app_factory() as s:
        async with s.begin():
            await set_rls_context(s, client_id=two_clients["a"], is_staff=False)
            assert await _visible_watchlist_clients(s, two_clients) == [two_clients["a"]]


async def test_staff_sees_all(app_factory, two_clients):
    async with app_factory() as s:
        async with s.begin():
            await set_rls_context(s, client_id=None, is_staff=True)
            assert await _visible_watchlist_clients(s, two_clients) == sorted(
                [two_clients["a"], two_clients["b"]]
            )


async def test_cross_client_write_rejected(app_factory, two_clients):
    async with app_factory() as s:
        with pytest.raises((IntegrityError, ProgrammingError, DBAPIError)):
            async with s.begin():
                await set_rls_context(s, client_id=two_clients["a"], is_staff=False)
                # Scoped to A, write for B → WITH CHECK violation.
                await s.execute(
                    text(
                        "INSERT INTO watchlists "
                        "(client_id, name, is_active, cadence, severity_threshold, "
                        " created_at, updated_at) "
                        "VALUES (:cid, 'evil', true, 'weekly', 'serious', now(), now())"
                    ),
                    {"cid": two_clients["b"]},
                )


async def test_privileged_role_bypasses(priv_factory, two_clients):
    async with priv_factory() as s:
        async with s.begin():
            assert await _visible_watchlist_clients(s, two_clients) == sorted(
                [two_clients["a"], two_clients["b"]]
            )


async def test_fr020_staff_cross_client_audit_attribution(app_factory, priv_factory, two_clients):
    """Staff context can write cross-client AND record an audit row naming the target client."""
    from app.audit.models import AuditLog

    event_type = f"rls_probe_{uuid.uuid4().hex[:8]}"
    async with app_factory() as s:
        async with s.begin():
            await set_rls_context(s, client_id=None, is_staff=True)  # staff/system context
            s.add(
                AuditLog(
                    actor_id=0,
                    actor_type="system",
                    action="rls_probe",
                    target=f"client:{two_clients['b']}",
                    event_type=event_type,
                    client_id=two_clients["b"],  # server-validated target client
                )
            )

    try:
        async with app_factory() as s:
            async with s.begin():
                await set_rls_context(s, client_id=None, is_staff=True)
                attributed = (
                    (
                        await s.execute(
                            select(AuditLog.client_id).where(AuditLog.event_type == event_type)
                        )
                    )
                    .scalars()
                    .first()
                )
        assert attributed == two_clients["b"]
    finally:
        async with priv_factory() as s:
            async with s.begin():
                await s.execute(delete(AuditLog).where(AuditLog.event_type == event_type))
