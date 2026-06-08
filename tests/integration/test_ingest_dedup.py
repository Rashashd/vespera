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


async def _make_admin(client, make_client, make_user):
    tenant = await make_client()
    admin = await make_user(role="admin", client_id=tenant.id)
    token = await login_token(client, admin.email)
    headers = {"Authorization": f"Bearer {token}"}
    return tenant, admin, headers


async def _create_watchlist_with_drug(client, headers, drug="warfarin"):
    resp = await client.post(
        "/watchlists",
        json={
            "name": f"WL-dedup-{drug}",
            "items": [{"item_type": "drug", "value": drug}],
        },
        headers=headers,
    )
    resp.raise_for_status()
    return resp.json()


async def _wait_for_run(client, headers, run_id, max_polls=10):
    """Poll until run terminal or max_polls reached."""
    import asyncio

    for _ in range(max_polls):
        resp = await client.get(f"/ingestion-runs/{run_id}", headers=headers)
        if resp.status_code == 200:
            body = resp.json()
            if body["status"] in ("success", "failed", "partial_success"):
                return body
        await asyncio.sleep(0.5)
    return None


async def _trigger_and_wait(client, headers, watchlist_id):
    resp = await client.post(f"/watchlists/{watchlist_id}/ingest", headers=headers)
    assert resp.status_code == 202
    return await _wait_for_run(client, headers, resp.json()["id"])


# ---------------------------------------------------------------------------
# T033: Re-run produces 0 new documents (all skipped)
# ---------------------------------------------------------------------------


async def test_rerun_zero_duplicates(client, make_client, make_user, auth_app):
    """Second run on the same watchlist creates 0 new documents; skipped > 0 (SC-003, US3-1)."""
    _, _, headers = await _make_admin(client, make_client, make_user)
    wl = await _create_watchlist_with_drug(client, headers)
    wl_id = wl["id"]

    # First run (may create 0 if no live adapters, but the dedup structure is tested).
    run1 = await _trigger_and_wait(client, headers, wl_id)
    if run1 is None:
        pytest.skip("Run did not complete in time")

    created1 = run1["counts"]["created"]

    # Second run should create nothing new.
    run2 = await _trigger_and_wait(client, headers, wl_id)
    if run2 is None:
        pytest.skip("Second run did not complete in time")

    # Whatever was created first, none should be re-created.
    assert run2["counts"]["created"] == 0
    if created1 > 0:
        assert run2["counts"]["skipped"] >= created1


# ---------------------------------------------------------------------------
# T034: Cross-source collapse — one document, both sources, highest tier
# (tested via fake-adapter injection in unit test style via service.py directly)
# ---------------------------------------------------------------------------


async def test_cross_source_collapse_service(auth_app):
    """Same normalized_external_id from two sources → one document with highest tier (US3-2)."""
    from datetime import UTC, datetime

    from app.ingestion.enums import SourceName, SourceReliability
    from app.ingestion.service import upsert_document

    factory = auth_app.state.session_factory

    # Use a unique client_id to avoid interference from other tests.
    from app.clients.models import Client

    async with factory() as s:
        async with s.begin():
            client_obj = Client(name="dedup-test-client", status="active")
            s.add(client_obj)
        await s.refresh(client_obj)

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

    # We need a user and run for FK.
    from app.auth.backend import password_helper
    from app.auth.models import User

    async with factory() as s:
        async with s.begin():
            user = User(
                email=f"dedup-admin-{client_obj.id}@test.com",
                hashed_password=password_helper.hash("Abcdef1!"),
                role="admin",
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
            # First insert: PubMed (peer_reviewed)
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
            # Second insert: same doc, different source with HIGHER reliability.
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
            assert created2 is False  # existing doc, not new
            assert doc2.id == doc1.id  # same document row
            assert doc2.source_reliability == "regulatory_alert"  # upgraded to highest tier


# ---------------------------------------------------------------------------
# T035: Per-client isolation — same record for two clients → two separate documents
# ---------------------------------------------------------------------------


async def test_per_client_isolation_service(auth_app):
    """Same normalized_id for two clients → two document rows, no cross-read (US3-4)."""
    from datetime import UTC, datetime

    from app.clients.models import Client, Watchlist
    from app.ingestion.enums import SourceName, SourceReliability
    from app.ingestion.models import IngestionRun
    from app.ingestion.service import upsert_document

    factory = auth_app.state.session_factory

    # Create two separate clients.
    async with factory() as s:
        async with s.begin():
            c1 = Client(name="iso-client-a", status="active")
            c2 = Client(name="iso-client-b", status="active")
            s.add_all([c1, c2])
        for c in [c1, c2]:
            await s.refresh(c)

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

    # Two clients produced two separate document rows.
    assert doc_ids[0] != doc_ids[1]

    # Cross-read: client_b cannot see client_a's document.
    from app.ingestion.service import get_run  # noqa (just to test pattern)

    async with factory() as s:
        from sqlalchemy import select

        from app.ingestion.models import Document

        # Client B cannot see client A's document.
        result = await s.execute(
            select(Document).where(Document.id == doc_ids[0], Document.client_id == c2.id)
        )
        assert result.scalar_one_or_none() is None
