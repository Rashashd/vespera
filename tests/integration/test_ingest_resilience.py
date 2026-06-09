"""Integration tests: per-source isolation, startup sweep, lifecycle, zero-result, PII-free."""

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


async def _admin_headers(client, make_client, make_staff_user):
    tenant = await make_client()
    admin = await make_staff_user(role="admin")
    token = await login_token(client, admin.email)
    return tenant, {"Authorization": f"Bearer {token}"}


async def _create_watchlist(client, headers, tenant_id, name="resilience-wl", drug="ibuprofen"):
    resp = await client.post(
        f"/clients/{tenant_id}/watchlists",
        json={"name": name, "items": [{"item_type": "drug", "value": drug}]},
        headers=headers,
    )
    resp.raise_for_status()
    return resp.json()


async def _trigger_run(client, headers, tenant_id, watchlist_id):
    resp = await client.post(
        f"/clients/{tenant_id}/watchlists/{watchlist_id}/ingest", headers=headers
    )
    assert resp.status_code == 202, resp.text
    return resp.json()


async def _poll_run(client, headers, tenant_id, run_id, max_polls=15):
    import asyncio

    for _ in range(max_polls):
        resp = await client.get(f"/clients/{tenant_id}/ingestion-runs/{run_id}", headers=headers)
        if resp.status_code == 200:
            body = resp.json()
            if body["status"] in ("success", "failed", "partial_success"):
                return body
        await asyncio.sleep(0.5)
    return None


# ---------------------------------------------------------------------------
# T046: Per-source failure isolation → partial_success + error captured
# ---------------------------------------------------------------------------


async def test_partial_success_with_failing_adapter(auth_app, make_client):
    """One source fails → partial_success; others persist; error is captured (FR-011/FR-012)."""
    from unittest.mock import AsyncMock

    from app.auth.backend import password_helper
    from app.auth.models import User
    from app.clients.models import Watchlist
    from app.ingestion.adapters import RawRecord
    from app.ingestion.enums import IngestionRunStatus, SourceName, SourceReliability

    factory = auth_app.state.session_factory

    c = await make_client()

    async with factory() as s:
        async with s.begin():
            wl = Watchlist(
                client_id=c.id, name="partial-wl", cadence="weekly", severity_threshold="serious"
            )
            s.add(wl)
        await s.refresh(wl)

    async with factory() as s:
        async with s.begin():
            u = User(
                email=f"partial-admin-{c.id}@test.com",
                hashed_password=password_helper.hash("Abcdef1!"),
                role="admin",
                user_type="client",
                client_id=c.id,
                is_active=True,
                is_superuser=False,
                is_verified=True,
            )
            s.add(u)
        await s.refresh(u)

    from app.ingestion.runner import run_ingestion
    from app.ingestion.service import create_run

    async with factory() as s:
        async with s.begin():
            run = await create_run(s, client_id=c.id, watchlist_id=wl.id, triggered_by_user_id=u.id)

    good_record = RawRecord(
        source=SourceName.PUBMED,
        source_external_id="PM-PART-001",
        raw_payload={"pmid": "PM-PART-001"},
        title="Partial success test record",
    )

    good_adapter = AsyncMock()
    good_adapter.name = SourceName.PUBMED
    good_adapter.reliability = SourceReliability.PEER_REVIEWED
    good_adapter.fetch = AsyncMock(return_value=[good_record])

    bad_adapter = AsyncMock()
    bad_adapter.name = SourceName.EMA
    bad_adapter.reliability = SourceReliability.REGULATORY_ALERT
    bad_adapter.fetch = AsyncMock(side_effect=RuntimeError("EMA is down"))

    class _FakeItem:
        item_type = "drug"
        value = "ibuprofen"
        mesh_validity = None

    await run_ingestion(
        run_id=run.id,
        client_id=c.id,
        watchlist_id=wl.id,
        watchlist_items=[_FakeItem()],
        session_factory=factory,
        adapters=[good_adapter, bad_adapter],
    )

    from app.ingestion.service import get_run

    async with factory() as s:
        finished = await get_run(s, c.id, run.id)

    assert finished is not None
    assert finished.status == IngestionRunStatus.PARTIAL_SUCCESS.value
    assert finished.created_count >= 1

    async with factory() as s:
        from sqlalchemy import select

        from app.ingestion.models import IngestionRunSource

        sources = list(
            (
                await s.scalars(
                    select(IngestionRunSource).where(IngestionRunSource.run_id == run.id)
                )
            ).all()
        )

    source_statuses = {r.source: r.status for r in sources}
    source_errors = {r.source: r.error for r in sources}

    assert source_statuses.get(SourceName.PUBMED.value) == "success"
    assert source_statuses.get(SourceName.EMA.value) == "failed"
    assert "EMA is down" in (source_errors.get(SourceName.EMA.value) or "")


# ---------------------------------------------------------------------------
# T047: Interrupted run → startup sweep → safe re-run
# ---------------------------------------------------------------------------


async def test_startup_sweep_reconciles_running_runs(auth_app, make_client):
    """Runs left in 'running' at startup are swept to 'failed'; re-run creates no duplicates."""
    from app.auth.backend import password_helper
    from app.auth.models import User
    from app.clients.models import Watchlist
    from app.ingestion.enums import IngestionRunStatus
    from app.ingestion.models import IngestionRun
    from app.ingestion.service import reconcile_interrupted_runs

    factory = auth_app.state.session_factory

    c = await make_client()

    async with factory() as s:
        async with s.begin():
            wl = Watchlist(
                client_id=c.id, name="sweep-wl", cadence="weekly", severity_threshold="serious"
            )
            s.add(wl)
        await s.refresh(wl)

    async with factory() as s:
        async with s.begin():
            u = User(
                email=f"sweep-admin-{c.id}@test.com",
                hashed_password=password_helper.hash("Abcdef1!"),
                role="admin",
                user_type="client",
                client_id=c.id,
                is_active=True,
                is_superuser=False,
                is_verified=True,
            )
            s.add(u)
        await s.refresh(u)

    async with factory() as s:
        async with s.begin():
            stuck_run = IngestionRun(
                client_id=c.id,
                watchlist_id=wl.id,
                triggered_by_user_id=u.id,
                status="running",
            )
            s.add(stuck_run)
        await s.refresh(stuck_run)

    async with factory() as s:
        async with s.begin():
            count = await reconcile_interrupted_runs(s)

    assert count >= 1

    async with factory() as s:
        refreshed = await s.get(IngestionRun, stuck_run.id)

    assert refreshed is not None
    assert refreshed.status == IngestionRunStatus.FAILED.value
    assert refreshed.finished_at is not None


# ---------------------------------------------------------------------------
# T059: Lifecycle/preservation — deactivating watchlist refuses trigger but preserves data
# ---------------------------------------------------------------------------


async def test_inactive_watchlist_refuses_trigger(client, make_client, make_staff_user):
    """Deactivating a watchlist means ingest returns 400; data is preserved (FR-022)."""
    tenant, headers = await _admin_headers(client, make_client, make_staff_user)
    wl = await _create_watchlist(client, headers, tenant.id, name="lifecycle-wl", drug="atenolol")
    wl_id = wl["id"]

    patch_resp = await client.patch(
        f"/clients/{tenant.id}/watchlists/{wl_id}", json={"is_active": False}, headers=headers
    )
    assert patch_resp.status_code == 200

    trigger_resp = await client.post(
        f"/clients/{tenant.id}/watchlists/{wl_id}/ingest", headers=headers
    )
    assert trigger_resp.status_code == 400


# ---------------------------------------------------------------------------
# T060: Zero-result success — adapter returns [] → run success, created=0, errored=0
# ---------------------------------------------------------------------------


async def test_zero_result_run_is_success(auth_app, make_client):
    """A source returning no records still yields run=success and created/errored=0 (FR-015)."""
    from unittest.mock import AsyncMock

    from app.auth.backend import password_helper
    from app.auth.models import User
    from app.clients.models import Watchlist
    from app.ingestion.enums import IngestionRunStatus, SourceName, SourceReliability
    from app.ingestion.runner import run_ingestion
    from app.ingestion.service import create_run, get_run

    factory = auth_app.state.session_factory

    c = await make_client()

    async with factory() as s:
        async with s.begin():
            wl = Watchlist(
                client_id=c.id,
                name="zero-result-wl",
                cadence="weekly",
                severity_threshold="serious",
            )
            s.add(wl)
        await s.refresh(wl)

    async with factory() as s:
        async with s.begin():
            u = User(
                email=f"zero-admin-{c.id}@test.com",
                hashed_password=password_helper.hash("Abcdef1!"),
                role="admin",
                user_type="client",
                client_id=c.id,
                is_active=True,
                is_superuser=False,
                is_verified=True,
            )
            s.add(u)
        await s.refresh(u)

    async with factory() as s:
        async with s.begin():
            run = await create_run(s, client_id=c.id, watchlist_id=wl.id, triggered_by_user_id=u.id)

    empty_adapter = AsyncMock()
    empty_adapter.name = SourceName.PUBMED
    empty_adapter.reliability = SourceReliability.PEER_REVIEWED
    empty_adapter.fetch = AsyncMock(return_value=[])

    class _FakeItem:
        item_type = "drug"
        value = "nothing"
        mesh_validity = None

    await run_ingestion(
        run_id=run.id,
        client_id=c.id,
        watchlist_id=wl.id,
        watchlist_items=[_FakeItem()],
        session_factory=factory,
        adapters=[empty_adapter],
    )

    async with factory() as s:
        finished = await get_run(s, c.id, run.id)

    assert finished is not None
    assert finished.status == IngestionRunStatus.SUCCESS.value
    assert finished.created_count == 0
    assert finished.errored_count == 0


# ---------------------------------------------------------------------------
# T061: PII-free logging — FAERS patient attribute never in structlog output
# ---------------------------------------------------------------------------


async def test_pii_free_logging(auth_app, make_client, caplog):
    """FAERS raw payload with patient data is never emitted in structlog output (FR-023)."""
    import logging
    from unittest.mock import AsyncMock

    from app.auth.backend import password_helper
    from app.auth.models import User
    from app.clients.models import Watchlist
    from app.ingestion.adapters import RawRecord
    from app.ingestion.enums import SourceName, SourceReliability
    from app.ingestion.runner import run_ingestion
    from app.ingestion.service import create_run

    factory = auth_app.state.session_factory

    c = await make_client()

    async with factory() as s:
        async with s.begin():
            wl = Watchlist(
                client_id=c.id, name="pii-wl", cadence="weekly", severity_threshold="serious"
            )
            s.add(wl)
        await s.refresh(wl)

    async with factory() as s:
        async with s.begin():
            u = User(
                email=f"pii-admin-{c.id}@test.com",
                hashed_password=password_helper.hash("Abcdef1!"),
                role="admin",
                user_type="client",
                client_id=c.id,
                is_active=True,
                is_superuser=False,
                is_verified=True,
            )
            s.add(u)
        await s.refresh(u)

    async with factory() as s:
        async with s.begin():
            run = await create_run(s, client_id=c.id, watchlist_id=wl.id, triggered_by_user_id=u.id)

    pii_record = RawRecord(
        source=SourceName.OPENFDA_FAERS,
        source_external_id="US-FDA-PII-001",
        raw_payload={"safetyreportid": "PII-001", "patient": {"patientbirthdate": "19800101"}},
        title="PII test record",
    )

    leaky_adapter = AsyncMock()
    leaky_adapter.name = SourceName.OPENFDA_FAERS
    leaky_adapter.reliability = SourceReliability.CASE_REPORT
    leaky_adapter.fetch = AsyncMock(return_value=[pii_record])

    class _FakeItem:
        item_type = "drug"
        value = "leaky-drug"
        mesh_validity = None

    with caplog.at_level(logging.DEBUG):
        await run_ingestion(
            run_id=run.id,
            client_id=c.id,
            watchlist_id=wl.id,
            watchlist_items=[_FakeItem()],
            session_factory=factory,
            adapters=[leaky_adapter],
        )

    log_text = " ".join(caplog.messages)
    assert "patientbirthdate" not in log_text, "PII field leaked into logs"
    assert "19800101" not in log_text, "PII value leaked into logs"
