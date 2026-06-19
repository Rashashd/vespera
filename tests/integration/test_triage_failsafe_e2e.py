"""End-to-end triage fail-safe tests (Constitution III): a classifier/NER outage must escalate or
mark the run degraded — never silently suppress, and never let a broken run complete clean.

Live stack only (skipped without PANTERA_INTEGRATION). These assert the SAFE outcomes the unit
tests assert in isolation, but against the real database + audit log + sweep queries.
"""

import os
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"), reason="integration tests require PANTERA_INTEGRATION=1"
)


@pytest_asyncio.fixture
async def outage_ms():
    """A ModelserverClient whose /classify always raises ModelserverError (classifier outage)."""
    from app.infra.modelserver_client import ModelserverClient, ModelserverError

    class OutageMS(ModelserverClient):
        async def classify(self, texts: list[str]) -> list[dict]:
            raise ModelserverError("classifier unreachable")

    return OutageMS(base_url="http://test", token="test-token")


@pytest.mark.asyncio
async def test_classifier_outage_escalates_end_to_end(
    auth_app, make_client, make_watchlist, make_document, monkeypatch, outage_ms
):
    """A classifier outage ESCALATES the finding (verdict=YES, resolution_path=escalated), with
    no classifier_version — it is never silently suppressed (audit C1 / Constitution III)."""
    from sqlalchemy import select

    import app.triage.ner as ner_mod
    from app.audit.models import AuditLog
    from app.triage.models import Finding
    from app.triage.runner import triage_document_runner

    async def fake_ner(text):
        return ["ibuprofen"], ["anaphylaxis"]

    monkeypatch.setattr(ner_mod, "extract_entities", fake_ner)

    client_obj = await make_client()
    wl = await make_watchlist(client_obj.id)
    doc = await make_document(
        client_id=client_obj.id, watchlist_id=wl.id, source_payload={"abstract": "x"}
    )

    factory = auth_app.state.session_factory
    dispatcher = auth_app.state.dispatcher

    await triage_document_runner(
        session_factory=factory,
        document_id=doc.id,
        client_id=client_obj.id,
        document_text="ibuprofen caused a fatal anaphylaxis reaction",
        source_reliability="peer_reviewed",
        watchlist_drugs=["ibuprofen"],
        custom_keywords=[],
        ms_client=outage_ms,
        dispatcher=dispatcher,
    )

    async with factory() as s:
        findings = (
            (await s.execute(select(Finding).where(Finding.document_id == doc.id))).scalars().all()
        )

    assert len(findings) == 1, "the outage must produce an escalation finding, not zero"
    f = findings[0]
    assert f.resolution_path == "escalated"
    assert f.classifier_version is None  # the classifier never ran
    assert f.bucket == "emergency"  # severity rule still applies ("fatal")
    assert f.status == "pending_expedited"  # human-visible, never suppressed

    # The escalation is auditable.
    async with factory() as s:
        rows = (
            (
                await s.execute(
                    select(AuditLog).where(
                        AuditLog.event_type == "FindingClassified",
                        AuditLog.client_id == client_obj.id,
                    )
                )
            )
            .scalars()
            .all()
        )
    assert any(r.payload and r.payload.get("finding_id") == f.id for r in rows)


@pytest.mark.asyncio
async def test_triage_failure_marks_cycle_degraded(auth_app, make_client, make_watchlist):
    """A triage-failed document in a cycle's index run makes the cycle complete DEGRADED, not
    clean: status stays 'completed' (partial report ships) but degraded_reason is set."""

    from app.embedding.models import DocumentIndexState, IndexBuildRun
    from app.ingestion.models import Document
    from app.scheduling.models import WatchlistCycle
    from app.scheduling.service import CycleService

    client_obj = await make_client()
    wl = await make_watchlist(client_obj.id)
    factory = auth_app.state.session_factory
    now = datetime.now(UTC)

    async with factory() as s:
        async with s.begin():
            run = IndexBuildRun(client_id=client_obj.id, watchlist_id=wl.id, status="success")
            s.add(run)
            await s.flush()
            cycle = WatchlistCycle(
                watchlist_id=wl.id,
                client_id=client_obj.id,
                status="in_progress",
                current_stage="consolidation",
                cadence_at_start="weekly",
                period_start=now,
                period_end=now,
                index_build_run_id=run.id,
            )
            s.add(cycle)
            doc = Document(
                client_id=client_obj.id,
                normalized_external_id=f"deg-{now.timestamp()}",
                source_reliability="peer_reviewed",
                title="degraded doc",
                summary="x",
                published_at=now,
            )
            s.add(doc)
            await s.flush()
            s.add(
                DocumentIndexState(
                    document_id=doc.id,
                    client_id=client_obj.id,
                    status="indexed",
                    last_run_id=run.id,
                    triage_failed_at=now,
                    triage_error="ner_unavailable",
                )
            )
            run_id, cycle_id, doc_id = run.id, cycle.id, doc.id

    try:
        async with factory() as s:
            assert await CycleService.cycle_has_degraded_triage(s, cycle_id) is True

        async with factory() as s:
            async with s.begin():
                await CycleService.mark_completed(s, cycle_id, degraded_reason="triage_failed")

        async with factory() as s:
            c = await s.get(WatchlistCycle, cycle_id)
            assert c.status == "completed"  # partial batch report still ships
            assert c.degraded_reason == "triage_failed"  # but it is NOT a clean 'all clear'
    finally:
        async with factory() as s:
            async with s.begin():
                await s.execute(delete_stmt(DocumentIndexState, "document_id", doc_id))
                await s.execute(delete_stmt(WatchlistCycle, "id", cycle_id))
                await s.execute(delete_stmt(Document, "id", doc_id))
                await s.execute(delete_stmt(IndexBuildRun, "id", run_id))


@pytest.mark.asyncio
async def test_sweep_finds_untriaged_and_orphaned(auth_app, make_client):
    """The sweep finders detect (a) an indexed-but-never-triaged document and (b) a finding stuck
    PENDING_EXPEDITED past the window — while ignoring a triaged document and a fresh finding."""

    from app.embedding.models import DocumentIndexState
    from app.ingestion.models import Document
    from app.triage.models import Finding
    from app.triage.sweep import find_orphaned_expedited, find_untriaged_documents

    client_obj = await make_client()
    factory = auth_app.state.session_factory
    now = datetime.now(UTC)
    old = now - timedelta(days=30)

    async with factory() as s:
        async with s.begin():
            stale_doc = Document(
                client_id=client_obj.id,
                normalized_external_id=f"stale-{now.timestamp()}",
                source_reliability="peer_reviewed",
                title="stale",
                summary="x",
                published_at=now,
            )
            clean_doc = Document(
                client_id=client_obj.id,
                normalized_external_id=f"clean-{now.timestamp()}",
                source_reliability="peer_reviewed",
                title="clean",
                summary="x",
                published_at=now,
            )
            s.add_all([stale_doc, clean_doc])
            await s.flush()
            # Indexed long ago, never triaged → flagged.
            s.add(
                DocumentIndexState(
                    document_id=stale_doc.id,
                    client_id=client_obj.id,
                    status="indexed",
                    triaged_at=None,
                    updated_at=old,
                )
            )
            # Indexed long ago BUT triaged (zero findings legitimately) → NOT flagged.
            s.add(
                DocumentIndexState(
                    document_id=clean_doc.id,
                    client_id=client_obj.id,
                    status="indexed",
                    triaged_at=now,
                    updated_at=old,
                )
            )
            orphan = Finding(
                client_id=client_obj.id,
                document_id=stale_doc.id,
                drug="ibuprofen",
                reaction="anaphylaxis",
                bucket="emergency",
                status="pending_expedited",
                resolution_path="escalated",
                updated_at=old,
            )
            fresh = Finding(
                client_id=client_obj.id,
                document_id=clean_doc.id,
                drug="ibuprofen",
                reaction="rash",
                bucket="urgent",
                status="pending_expedited",
                resolution_path="model",
                updated_at=now,
            )
            s.add_all([orphan, fresh])
            await s.flush()
            stale_id, clean_id, orphan_id, fresh_id = (
                stale_doc.id,
                clean_doc.id,
                orphan.id,
                fresh.id,
            )

    async with factory() as s:
        untriaged = {d for d, _c in await find_untriaged_documents(s)}
        orphaned = {f for f, _c in await find_orphaned_expedited(s)}

    assert stale_id in untriaged  # never triaged + stale → flagged
    assert clean_id not in untriaged  # triaged (zero findings) → not flagged (noise-free)
    assert orphan_id in orphaned  # PENDING_EXPEDITED past the window → flagged
    assert fresh_id not in orphaned  # fresh PENDING_EXPEDITED (mid-flight) → not flagged


@pytest.mark.asyncio
async def test_real_ner_failure_marks_document_degraded(
    auth_app, make_client, make_watchlist, make_document, monkeypatch, mock_modelserver_client
):
    """A REAL NER failure (the model itself fails — extract_entities is NOT mocked) marks the
    document degraded (triage_failed_at set), never silently swallowed."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    import app.triage.ner as ner_mod
    from app.clients.models import WatchlistItem
    from app.embedding.models import DocumentIndexState
    from app.embedding.triage_trigger import trigger_triage
    from app.ingestion.models import Document

    def _boom():
        raise OSError("ner model artifact missing")

    # Patch the model LOAD, not extract_entities — the real NerUnavailable path is exercised.
    monkeypatch.setattr(ner_mod, "_get_nlp", _boom)

    client_obj = await make_client()
    wl = await make_watchlist(client_obj.id)
    factory = auth_app.state.session_factory

    async with factory() as s:
        async with s.begin():
            s.add(
                WatchlistItem(
                    watchlist_id=wl.id,
                    client_id=client_obj.id,
                    item_type="drug",
                    value="ibuprofen",
                    normalized_value="ibuprofen",
                )
            )

    doc = await make_document(client_id=client_obj.id, watchlist_id=wl.id)

    async with factory() as s:
        document = (
            await s.execute(
                select(Document)
                .options(selectinload(Document.provenance))
                .where(Document.id == doc.id)
            )
        ).scalar_one()

    await trigger_triage(
        session_factory=factory,
        document=document,
        chunk_texts=["ibuprofen caused anaphylaxis"],
        client_id=client_obj.id,
        modelserver_client=mock_modelserver_client,
        dispatcher=auth_app.state.dispatcher,
        app_state=None,
    )

    async with factory() as s:
        state = (
            await s.execute(
                select(DocumentIndexState).where(DocumentIndexState.document_id == doc.id)
            )
        ).scalar_one()

    assert state.triage_failed_at is not None  # degraded marker recorded
    assert state.triage_error == "ner_unavailable"
    assert state.triaged_at is None  # NOT marked as successfully triaged


def delete_stmt(model, col, value):
    """Small helper: DELETE FROM model WHERE col = value (avoids importing delete in each test)."""
    from sqlalchemy import delete

    return delete(model).where(getattr(model, col) == value)
