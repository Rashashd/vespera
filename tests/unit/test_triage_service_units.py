"""Unit tests for triage orchestration + routing branches the pipeline integration test skips.

Covers triage_document's early-exit paths (no watchlist drug match; all matches incidental),
_triage_one's idempotent-finding branch (upsert reports an existing row), and upsert_finding's
ON CONFLICT path (insert returns no row -> fetch the existing id). All fakes; no live DB.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog

from app.triage import service as svc
from app.triage.enums import Bucket
from app.triage.routing import upsert_finding

pytestmark = pytest.mark.asyncio


async def test_triage_document_no_drug_match_returns_empty(monkeypatch):
    """Extracted drugs that are not on the watchlist → no findings, session untouched."""
    monkeypatch.setattr(svc, "extract_entities", AsyncMock(return_value=(["aspirin"], ["nausea"])))
    outcomes = await svc.triage_document(
        session=AsyncMock(),
        document_id=1,
        client_id=1,
        document_text="text",
        source_reliability="peer_reviewed",
        watchlist_drugs=["ibuprofen"],  # aspirin not watched
        custom_keywords=[],
        ms_client=MagicMock(),
        settings=MagicMock(),
        dispatcher=AsyncMock(),
    )
    assert outcomes == []


async def test_triage_document_all_incidental_returns_empty(monkeypatch):
    """A watchlist drug present but only incidentally mentioned → filtered to no findings."""
    monkeypatch.setattr(svc, "extract_entities", AsyncMock(return_value=(["aspirin"], ["nausea"])))
    monkeypatch.setattr(svc.prefilter, "filter_substantive_drugs", AsyncMock(return_value=[]))
    outcomes = await svc.triage_document(
        session=AsyncMock(),
        document_id=1,
        client_id=1,
        document_text="text",
        source_reliability="peer_reviewed",
        watchlist_drugs=["aspirin"],
        custom_keywords=[],
        ms_client=MagicMock(),
        settings=MagicMock(),
        dispatcher=AsyncMock(),
    )
    assert outcomes == []


async def test_triage_one_idempotent_existing_finding(monkeypatch):
    """When upsert reports an existing row (created=False), no audit event is dispatched."""
    monkeypatch.setattr(svc, "resolve_adverse", AsyncMock(return_value=(True, 0.9, "model", "v1")))
    monkeypatch.setattr(svc, "upsert_finding", AsyncMock(return_value=(7, False)))
    dispatcher = AsyncMock()

    outcome = await svc._triage_one(
        session=AsyncMock(),
        document_id=1,
        client_id=1,
        drug="aspirin",
        reaction="nausea",
        document_text="Patient experienced death after the dose.",
        source_reliability="peer_reviewed",
        custom_keywords=[],
        ms_client=MagicMock(),
        settings=MagicMock(),
        dispatcher=dispatcher,
        log=structlog.get_logger("test"),
    )

    assert outcome.finding_id == 7
    assert outcome.created is False
    dispatcher.dispatch.assert_not_called()  # created=False → no FindingClassified


async def test_upsert_finding_conflict_returns_existing_id():
    """ON CONFLICT DO NOTHING returns no row → fetch and return the existing finding id."""
    session = AsyncMock()
    insert_result = MagicMock()
    insert_result.fetchone = MagicMock(return_value=None)  # conflict: nothing inserted
    select_result = MagicMock()
    select_result.scalar_one = MagicMock(return_value=42)
    session.execute = AsyncMock(side_effect=[insert_result, select_result])

    finding_id, created = await upsert_finding(
        session,
        client_id=1,
        document_id=1,
        drug="aspirin",
        reaction="nausea",
        bucket=Bucket.MINOR,
        resolution_path="model",
        model_confidence=0.8,
    )
    assert (finding_id, created) == (42, False)
