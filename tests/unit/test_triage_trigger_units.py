"""Unit tests for after-index triage-trigger branches not hit by the e2e failsafe test.

Covers the non-NER failure code, the best-effort degraded/succeeded marker-write except paths
(a marker write must never crash the index loop), and the no-watchlist-drugs early exit (which
marks the document triaged so the staleness sweep won't re-flag it). Fakes only; no live DB.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import app.embedding.triage_trigger as trigger_mod
from app.embedding.triage_trigger import (
    _failure_code,
    _mark_triage_degraded,
    _mark_triage_succeeded,
)

pytestmark = pytest.mark.asyncio


def test_failure_code_non_ner_uses_exception_class_name():
    assert _failure_code(ValueError("boom")) == "ValueError"


async def test_mark_triage_degraded_swallows_marker_write_failure():
    """A failure recording the degraded marker is logged/alerted, never raised (index loop safe)."""

    def bad_factory():
        raise RuntimeError("db unavailable")

    # Must not raise even though the session factory blows up.
    await _mark_triage_degraded(bad_factory, MagicMock(id=1), 1, ValueError("orig"))


async def test_mark_triage_succeeded_swallows_marker_write_failure():
    def bad_factory():
        raise RuntimeError("db unavailable")

    await _mark_triage_succeeded(bad_factory, MagicMock(id=1), 1)


async def test_trigger_triage_no_watchlist_drugs_marks_succeeded(monkeypatch):
    """A document whose watchlists carry no drug items is marked triaged and short-circuits."""
    mark = AsyncMock()
    monkeypatch.setattr(trigger_mod, "_mark_triage_succeeded", mark)
    factory = MagicMock()
    document = MagicMock(id=1, provenance=[], source_reliability="peer_reviewed")

    await trigger_mod.trigger_triage(
        session_factory=factory,  # no watchlist ids → the DB block is skipped entirely
        document=document,
        chunk_texts=["some text"],
        client_id=1,
        modelserver_client=MagicMock(),
        dispatcher=AsyncMock(),
    )

    mark.assert_awaited_once()
    factory.assert_not_called()  # short-circuited before any DB session was opened


class _FakeSessionCM:
    """Async context manager yielding a fake session for the watchlist-lookup block."""

    def __init__(self, session) -> None:
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


async def test_trigger_triage_success_marks_and_enqueues(monkeypatch):
    """Watchlist has drug items → triage runs, the document is marked triaged, and expedited
    drafts are enqueued (the success tail after the after-index hook)."""
    fake_session = AsyncMock()
    items_result = MagicMock(scalars=lambda: MagicMock(all=lambda: [MagicMock(value="aspirin")]))
    client_result = MagicMock(
        scalar_one_or_none=lambda: MagicMock(
            custom_severity_keywords=[{"keyword": "x", "tier": "serious"}]
        )
    )
    fake_session.execute = AsyncMock(side_effect=[items_result, client_result])

    monkeypatch.setattr(
        "app.triage.runner.triage_document_runner", AsyncMock(return_value=[MagicMock()])
    )
    mark = AsyncMock()
    monkeypatch.setattr(trigger_mod, "_mark_triage_succeeded", mark)
    enqueue = AsyncMock()
    monkeypatch.setattr(trigger_mod, "_enqueue_expedited_drafts", enqueue)

    document = MagicMock(
        id=1, source_reliability="peer_reviewed", provenance=[MagicMock(watchlist_id=5)]
    )

    await trigger_mod.trigger_triage(
        session_factory=lambda: _FakeSessionCM(fake_session),
        document=document,
        chunk_texts=["text about aspirin"],
        client_id=1,
        modelserver_client=MagicMock(),
        dispatcher=AsyncMock(),
        app_state=MagicMock(),  # non-None → expedited enqueue path runs
    )

    mark.assert_awaited_once()
    enqueue.assert_awaited_once()


async def test_trigger_triage_missing_client_row_skips_custom_keywords(monkeypatch):
    """The watchlist has drugs but the client row is gone → custom keywords stay empty, no crash."""
    fake_session = AsyncMock()
    items_result = MagicMock(scalars=lambda: MagicMock(all=lambda: [MagicMock(value="aspirin")]))
    client_result = MagicMock(scalar_one_or_none=lambda: None)  # client row missing
    fake_session.execute = AsyncMock(side_effect=[items_result, client_result])

    monkeypatch.setattr("app.triage.runner.triage_document_runner", AsyncMock(return_value=[]))
    mark = AsyncMock()
    monkeypatch.setattr(trigger_mod, "_mark_triage_succeeded", mark)

    document = MagicMock(
        id=1, source_reliability="peer_reviewed", provenance=[MagicMock(watchlist_id=5)]
    )

    await trigger_mod.trigger_triage(
        session_factory=lambda: _FakeSessionCM(fake_session),
        document=document,
        chunk_texts=["text about aspirin"],
        client_id=1,
        modelserver_client=MagicMock(),
        dispatcher=AsyncMock(),
        app_state=None,  # None → skip enqueue path
    )

    mark.assert_awaited_once()
