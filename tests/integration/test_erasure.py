"""Right-to-erasure (Cluster 3 / B1, Constitution V): purge rows + vectors + sessions, retain a
minimal tombstone, audit-log the action + dispatch ClientErased. Live stack only."""

import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"), reason="integration tests require PANTERA_INTEGRATION=1"
)


@pytest.mark.asyncio
async def test_erase_client_purges_all_and_retains_tombstone(
    auth_app,
    authed_manager_client,
    make_client,
    make_watchlist,
    make_document,
    make_user,
    priv_factory,
):
    """Erasure purges every client-scoped row (vectors + sessions), keeps the tombstone, and
    leaves the audit trail intact (prior rows retained + a ClientErased row added)."""
    from sqlalchemy import func, select

    from app.audit.models import AuditLog
    from app.auth.models import User
    from app.clients.models import Client, WatchlistItem
    from app.db.base import Base
    from app.embedding.models import Chunk
    from app.triage.models import Finding

    name = f"EraseMe-{uuid.uuid4().hex[:8]}"
    c = await make_client(name=name)
    wl = await make_watchlist(c.id)
    doc = await make_document(client_id=c.id, watchlist_id=wl.id)
    client_user = await make_user(role="client_user", client_id=c.id)  # a session (stateless JWT)

    async with priv_factory() as s:
        async with s.begin():
            s.add(
                WatchlistItem(
                    watchlist_id=wl.id,
                    client_id=c.id,
                    item_type="drug",
                    value="ibuprofen",
                    normalized_value="ibuprofen",
                )
            )
            s.add(
                Chunk(  # a vector
                    client_id=c.id,
                    document_id=doc.id,
                    ordinal=0,
                    chunk_type="text",
                    source_reliability="peer_reviewed",
                    text="patient text",
                    embedding=[0.1] * 768,
                    embedder_version="test",
                )
            )
            s.add(
                Finding(
                    client_id=c.id,
                    document_id=doc.id,
                    drug="ibuprofen",
                    reaction="rash",
                    bucket="minor",
                    status="pending_batch",
                    resolution_path="model",
                )
            )

    # A prior audited action, so we can prove the audit trail is RETAINED through erasure.
    suspend = await authed_manager_client.post(f"/clients/{c.id}/suspend")
    assert suspend.status_code == 200

    # Erase (manager auth + exact-name confirmation).
    resp = await authed_manager_client.post(f"/clients/{c.id}/erase", json={"confirm_name": name})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "erased"
    assert body["name"] == name  # tombstone keeps the relationship identity
    assert body["report_email_regular"] is None  # PII scrubbed
    assert body["erased_at"] is not None

    async with priv_factory() as s:
        # COMPLETE purge: every client_id table EXCEPT the tombstone + retained audit_log is empty.
        for table in Base.metadata.sorted_tables:
            if table.name in {"clients", "audit_log"} or "client_id" not in table.c:
                continue
            n = await s.scalar(
                select(func.count()).select_from(table).where(table.c.client_id == c.id)
            )
            assert n == 0, f"{table.name} still has {n} row(s) for the erased client"

        # Vectors (chunks) + session (client-user) specifically gone.
        assert (
            await s.scalar(select(func.count()).select_from(Chunk).where(Chunk.client_id == c.id))
        ) == 0
        assert (await s.get(User, client_user.id)) is None

        # Tombstone retained.
        tomb = await s.get(Client, c.id)
        assert tomb is not None
        assert tomb.status == "erased" and tomb.name == name and tomb.erased_at is not None

        # Audit trail retained (prior ClientSuspended) + the erasure recorded (ClientErased),
        # both tenant-scoped to the erased client.
        rows = (await s.execute(select(AuditLog).where(AuditLog.client_id == c.id))).scalars().all()
        events = {r.event_type for r in rows}
        assert "ClientSuspended" in events  # prior audit RETAINED, not purged
        assert "ClientErased" in events  # erasure audited
        erased_row = next(r for r in rows if r.event_type == "ClientErased")
        assert erased_row.payload.get("erased_client_id") == c.id


@pytest.mark.asyncio
async def test_erase_requires_name_confirmation_and_rejects_double_erase(
    auth_app, authed_manager_client, make_client
):
    """Wrong/absent name confirmation → 400 (no purge); re-erasing a tombstone → 409."""
    name = f"Acme-{uuid.uuid4().hex[:8]}"
    c = await make_client(name=name)

    bad = await authed_manager_client.post(
        f"/clients/{c.id}/erase", json={"confirm_name": "wrong-name"}
    )
    assert bad.status_code == 400

    ok = await authed_manager_client.post(f"/clients/{c.id}/erase", json={"confirm_name": name})
    assert ok.status_code == 200

    again = await authed_manager_client.post(f"/clients/{c.id}/erase", json={"confirm_name": name})
    assert again.status_code == 409
