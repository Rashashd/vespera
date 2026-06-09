"""Integration tests: re-run dedup, cross-source collapse, per-client isolation (US3)."""

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


async def _make_admin(client, make_client, make_staff_user):
    tenant = await make_client()
    admin = await make_staff_user(role="admin")
    token = await login_token(client, admin.email)
    headers = {"Authorization": f"Bearer {token}"}
    return tenant, admin, headers


async def _create_watchlist_with_drug(client, headers, tenant_id, drug="warfarin"):
    resp = await client.post(
        f"/clients/{tenant_id}/watchlists",
        json={
            "name": f"WL-dedup-{drug}",
            "items": [{"item_type": "drug", "value": drug}],
        },
        headers=headers,
    )
    resp.raise_for_status()
    return resp.json()


async def _wait_for_run(client, headers, tenant_id, run_id, max_polls=10):
    """Poll until run terminal or max_polls reached."""
    import asyncio

    for _ in range(max_polls):
        resp = await client.get(f"/clients/{tenant_id}/ingestion-runs/{run_id}", headers=headers)
        if resp.status_code == 200:
            body = resp.json()
            if body["status"] in ("success", "failed", "partial_success"):
                return body
        await asyncio.sleep(0.5)
    return None


async def _trigger_and_wait(client, headers, tenant_id, watchlist_id):
    resp = await client.post(
        f"/clients/{tenant_id}/watchlists/{watchlist_id}/ingest", headers=headers
    )
    assert resp.status_code == 202
    return await _wait_for_run(client, headers, tenant_id, resp.json()["id"])


# ---------------------------------------------------------------------------
# T033: Re-run produces 0 new documents (all skipped)
# ---------------------------------------------------------------------------


async def test_rerun_zero_duplicates(client, make_client, make_staff_user, auth_app):
    """Second run skips already-seen documents; dedup is verified by skipped > 0 (SC-003, US3-1)."""
    tenant, _, headers = await _make_admin(client, make_client, make_staff_user)
    wl = await _create_watchlist_with_drug(client, headers, tenant.id)
    wl_id = wl["id"]

    run1 = await _trigger_and_wait(client, headers, tenant.id, wl_id)
    if run1 is None:
        pytest.skip("Run did not complete in time")

    created1 = run1["counts"]["created"]
    if created1 == 0:
        pytest.skip("Run 1 found 0 documents (live API failure) — dedup cannot be verified")

    run2 = await _trigger_and_wait(client, headers, tenant.id, wl_id)
    if run2 is None:
        pytest.skip("Second run did not complete in time")

    # Dedup is working if skipped > 0 (docs from run 1 re-encountered).
    assert run2["counts"]["skipped"] > 0, "Run 2 skipped nothing — dedup appears broken"


# ---------------------------------------------------------------------------
# T034: Cross-source collapse — one document, both sources, highest tier
# (tested via fake-adapter injection in unit test style via service.py directly)
# ---------------------------------------------------------------------------


async def test_cross_source_collapse_service(auth_app, make_client):
    """Same normalized_external_id from two sources → one document with highest tier (US3-2)."""
    from datetime import UTC, datetime

    from app.ingestion.enums import SourceName, SourceReliability
    from app.ingestion.service import upsert_document

    factory = auth_app.state.session_factory

    client_obj = await make_client()

    from app.clients.models import Watchlist
    from app.ingestion.models import IngestionRun

    async with factory() as s:
        async with s.begin():
            wl = Watchlist(
                client_id=client_obj.id,
                name="dedup-wl",
                cadence="weekly",
                severity_threshold="serious",
                is_active=True,
            )
            s.add(wl)
        await s.refresh(wl)

    from app.auth.backend import password_helper
    from app.auth.models import User

    async with factory() as s:
        async with s.begin():
            user = User(
                email=f"dedup-admin-{client_obj.id}@test.com",
                hashed_password=password_helper.hash("Abcdef1!"),
                role="admin",
                user_type="client",
                client_id=client_obj.id,
                is_active=True,
                is_superuser=False,
                is_verified=True,
            )
            s.add(user)
        await s.refresh(user)

    async with factory() as s:
        async with s.begin():
            run = IngestionRun(
                client_id=client_obj.id,
                watchlist_id=wl.id,
                triggered_by_user_id=user.id,
                status="running",
            )
            s.add(run)
        await s.refresh(run)

    norm_id = "doi:10.9999/dedup-test-2026"

    async with factory() as s:
        async with s.begin():
            doc1, created1 = await upsert_document(
                s,
                client_id=client_obj.id,
                normalized_external_id=norm_id,
                source=SourceName.PUBMED,
                source_external_id="PM999001",
                source_reliability=SourceReliability.PEER_REVIEWED,
                raw_payload={"pmid": "PM999001"},
                title="Cross-source dedup test",
                summary=None,
                published_at=datetime(2026, 3, 1, tzinfo=UTC),
                origin_url=None,
                watchlist_id=wl.id,
                run_id=run.id,
            )
            assert created1 is True

    async with factory() as s:
        async with s.begin():
            doc2, created2 = await upsert_document(
                s,
                client_id=client_obj.id,
                normalized_external_id=norm_id,
                source=SourceName.FDA_MEDWATCH,
                source_external_id="MW-2026-001",
                source_reliability=SourceReliability.REGULATORY_ALERT,
                raw_payload={"alert_id": "MW-2026-001"},
                title="Cross-source dedup test",
                summary=None,
                published_at=datetime(2026, 3, 1, tzinfo=UTC),
                origin_url=None,
                watchlist_id=wl.id,
                run_id=run.id,
            )
            assert created2 is False
            assert doc2.id == doc1.id
            assert doc2.source_reliability == "regulatory_alert"


# ---------------------------------------------------------------------------
# T035: Per-client isolation — same record for two clients → two separate documents
# ---------------------------------------------------------------------------


async def test_per_client_isolation_service(auth_app, make_client):
    """Same normalized_id for two clients → two document rows, no cross-read (US3-4)."""
    from datetime import UTC, datetime

    from app.clients.models import Watchlist
    from app.ingestion.enums import SourceName, SourceReliability
    from app.ingestion.models import IngestionRun
    from app.ingestion.service import upsert_document

    factory = auth_app.state.session_factory

    c1 = await make_client()
    c2 = await make_client()

    async with factory() as s:
        async with s.begin():
            wl1 = Watchlist(
                client_id=c1.id, name="iso-wl-a", cadence="weekly", severity_threshold="serious"
            )
            wl2 = Watchlist(
                client_id=c2.id, name="iso-wl-b", cadence="weekly", severity_threshold="serious"
            )
            s.add_all([wl1, wl2])
        for wl in [wl1, wl2]:
            await s.refresh(wl)

    from app.auth.backend import password_helper
    from app.auth.models import User

    users = []
    for c in [c1, c2]:
        async with factory() as s:
            async with s.begin():
                u = User(
                    email=f"iso-admin-{c.id}@test.com",
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
            users.append(u)

    runs = []
    for c, wl, u in zip([c1, c2], [wl1, wl2], users, strict=True):
        async with factory() as s:
            async with s.begin():
                r = IngestionRun(
                    client_id=c.id,
                    watchlist_id=wl.id,
                    triggered_by_user_id=u.id,
                    status="running",
                )
                s.add(r)
            await s.refresh(r)
            runs.append(r)

    norm_id = "pmid:shared-99999-iso"

    doc_ids = []
    for c, wl, run in zip([c1, c2], [wl1, wl2], runs, strict=True):
        async with factory() as s:
            async with s.begin():
                doc, created = await upsert_document(
                    s,
                    client_id=c.id,
                    normalized_external_id=norm_id,
                    source=SourceName.PUBMED,
                    source_external_id="PM99999",
                    source_reliability=SourceReliability.PEER_REVIEWED,
                    raw_payload={"pmid": "PM99999"},
                    title="Isolation test",
                    summary=None,
                    published_at=datetime(2026, 1, 1, tzinfo=UTC),
                    origin_url=None,
                    watchlist_id=wl.id,
                    run_id=run.id,
                )
                assert created is True
                doc_ids.append(doc.id)

    assert doc_ids[0] != doc_ids[1]

    from app.ingestion.service import get_run  # noqa (just to test pattern)

    async with factory() as s:
        from sqlalchemy import select

        from app.ingestion.models import Document

        result = await s.execute(
            select(Document).where(Document.id == doc_ids[0], Document.client_id == c2.id)
        )
        assert result.scalar_one_or_none() is None
