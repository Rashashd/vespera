"""Fail-safe and failure-matrix unit tests (US4, FR-018/FR-019, SC-007)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.infra.modelserver_client import ModelserverError
from app.triage.classify import resolve_adverse

# ---------------------------------------------------------------------------
# LLM fail-safe paths (no session/DB needed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_low_conf_llm_failure_escalates():
    """Low confidence + LLM resolve raises → verdict=True, resolution_path='escalated'."""
    ms_client = AsyncMock()
    ms_client.classify.return_value = [{"confidence": 0.40, "is_adverse": False}]

    settings = MagicMock()
    settings.triage_confidence_threshold = 0.70

    async def failing_llm_resolve(text, reliability):
        raise RuntimeError("LLM timeout")

    verdict, confidence, path, classifier_version = await resolve_adverse(
        text="Some finding text.",
        ms_client=ms_client,
        settings=settings,
        llm_resolve_fn=failing_llm_resolve,
        source_reliability="peer_reviewed",
        client_id=1,
        document_id=1,
    )

    assert verdict is True
    assert confidence is None
    assert path == "escalated"


@pytest.mark.asyncio
async def test_low_conf_llm_success_verdict_followed():
    """Low confidence + LLM resolves successfully → LLM verdict used, path='llm'."""
    ms_client = AsyncMock()
    ms_client.classify.return_value = [{"confidence": 0.45, "is_adverse": True}]

    settings = MagicMock()
    settings.triage_confidence_threshold = 0.70

    async def llm_resolve_false(text, reliability):
        return False

    verdict, confidence, path, classifier_version = await resolve_adverse(
        text="Some text.",
        ms_client=ms_client,
        settings=settings,
        llm_resolve_fn=llm_resolve_false,
        source_reliability="peer_reviewed",
        client_id=1,
        document_id=1,
    )

    assert verdict is False
    assert confidence is None
    assert path == "llm"


@pytest.mark.asyncio
async def test_valence_llm_failure_defaults_to_positive():
    """assess_valence LLM failure → returns 'positive' (FR-016 fail-safe)."""
    settings = MagicMock()
    settings.triage_llm_max_tokens = 64
    settings.triage_confidence_threshold = 0.70
    llm = MagicMock()
    llm.provider = "anthropic"
    llm.model = "claude-3-haiku-20240307"
    llm.api_key = "test-key"

    with (
        patch("app.triage.llm.build_llm_client", return_value=llm),
        patch("app.triage.llm._call_llm", side_effect=RuntimeError("timeout")),
    ):
        from app.triage.llm import assess_valence

        result = await assess_valence(
            text="Some document.",
            source_reliability="peer_reviewed",
            settings=settings,
            client_id=1,
            document_id=1,
        )

    assert result == "positive"


# ---------------------------------------------------------------------------
# Classifier (ModelserverError) failure — service._triage_one must ESCALATE the
# pair (verdict=YES, resolution_path="escalated"), NEVER silently suppress it
# (Constitution III). Severity bucketing still runs during the outage.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classifier_outage_escalates_not_suppressed():
    """ModelserverError (classifier down) → the pair is escalated, NOT dropped.

    A classifier OUTAGE must escalate (verdict=YES, resolution_path="escalated"), never return
    None / skip the finding. Severity bucketing still runs, so an emergency keyword still routes
    PENDING_EXPEDITED — and the operator alert is still emitted so the outage is visible to ops.
    """
    from app.triage.enums import Bucket, FindingStatus
    from app.triage.service import _triage_one

    ms_client = AsyncMock()
    ms_client.classify.side_effect = ModelserverError("modelserver unreachable")

    session = AsyncMock()
    dispatcher = AsyncMock()
    settings = MagicMock()
    settings.triage_confidence_threshold = 0.70
    log = MagicMock()

    with patch(
        "app.triage.service.upsert_finding",
        new=AsyncMock(return_value=(123, True)),
    ):
        result = await _triage_one(
            session=session,
            document_id=42,
            client_id=7,
            drug="ibuprofen",
            reaction="anaphylaxis",
            document_text="Patient suffered anaphylaxis after ibuprofen.",
            source_reliability="peer_reviewed",
            custom_keywords=[],
            ms_client=ms_client,
            settings=settings,
            dispatcher=dispatcher,
            log=log,
        )

    # SAFE outcome: a finding exists, escalated, and human-visible — never suppressed.
    assert result is not None
    assert result.resolution_path == "escalated"
    assert result.model_confidence is None
    assert result.finding_id == 123
    assert result.bucket == Bucket.EMERGENCY  # "anaphylaxis" is an ICH emergency keyword
    assert result.status == FindingStatus.PENDING_EXPEDITED

    # Operator alert still emitted (stage=classify) so the outage pages, not just suppresses.
    log.error.assert_called_once()
    alert = log.error.call_args
    assert alert.args[0] == "triage.operator_alert"
    assert alert.kwargs["stage"] == "classify"

    # The finding's audit event records the escalation outcome.
    dispatcher.dispatch.assert_awaited_once()
    event = dispatcher.dispatch.call_args.args[0]
    assert event.resolution_path == "escalated"
    assert event.routing_outcome == FindingStatus.PENDING_EXPEDITED.value
    # A classifier OUTAGE has no version (distinguishes it from a low-confidence escalation).
    assert event.classifier_version is None


# ---------------------------------------------------------------------------
# Persist (DB) failure — service._triage_one must log operator_alert and re-raise.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_persist_error_logs_alert_and_reraises():
    """DB upsert failure → operator_alert (stage=persist) + exception re-raised for rollback."""
    from app.triage.service import _triage_one

    ms_client = AsyncMock()
    ms_client.classify.return_value = [{"confidence": 0.95, "is_adverse": True}]

    session = AsyncMock()
    dispatcher = AsyncMock()
    settings = MagicMock()
    settings.triage_confidence_threshold = 0.70
    log = MagicMock()

    with patch(
        "app.triage.service.upsert_finding",
        side_effect=Exception("DB connection lost"),
    ):
        with pytest.raises(Exception, match="DB connection lost"):
            await _triage_one(
                session=session,
                document_id=42,
                client_id=7,
                drug="ibuprofen",
                reaction="bleeding",
                document_text="Patient had bleeding after ibuprofen.",
                source_reliability="peer_reviewed",
                custom_keywords=[],
                ms_client=ms_client,
                settings=settings,
                dispatcher=dispatcher,
                log=log,
            )

    log.error.assert_called_once()
    call_kwargs = log.error.call_args
    assert call_kwargs[0][0] == "triage.operator_alert"
    assert call_kwargs[1]["stage"] == "persist"


# ---------------------------------------------------------------------------
# High-confidence model path (sanity baseline)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_high_confidence_model_verdict_no_llm():
    """confidence >= threshold → model verdict used directly, no LLM call."""
    ms_client = AsyncMock()
    ms_client.classify.return_value = [
        {"confidence": 0.92, "is_adverse": True, "model_version": {"sha256": "clf-sha-001"}}
    ]

    settings = MagicMock()
    settings.triage_confidence_threshold = 0.70

    llm_called = False

    async def should_not_be_called(text, reliability):
        nonlocal llm_called
        llm_called = True
        return True

    verdict, confidence, path, classifier_version = await resolve_adverse(
        text="Patient had seizure.",
        ms_client=ms_client,
        settings=settings,
        llm_resolve_fn=should_not_be_called,
        source_reliability="peer_reviewed",
        client_id=1,
        document_id=1,
    )

    assert verdict is True
    assert confidence == pytest.approx(0.92)
    assert path == "model"
    assert classifier_version == "clf-sha-001"  # SHA propagated from the classify result
    assert llm_called is False


# ---------------------------------------------------------------------------
# NER failure — extract_entities must raise NerUnavailable (a loud, typed signal),
# never a silent ([], []) result; triage_document must surface it, not swallow it.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ner_failure_raises_not_silent_empty():
    """NER model load/exec failure → NerUnavailable, never a silent ([], []) result.

    A silent empty result is indistinguishable from 'no entities found', so the document would
    be dropped with zero findings (Constitution III). NER failure must be a loud, typed signal.
    """
    from app.triage.ner import NerUnavailable, extract_entities

    with patch("app.triage.ner._get_nlp", side_effect=OSError("model artifact missing")):
        with pytest.raises(NerUnavailable):
            await extract_entities("Patient took ibuprofen and developed anaphylaxis.")


@pytest.mark.asyncio
async def test_triage_document_surfaces_ner_failure():
    """triage_document re-raises NerUnavailable + emits operator_alert (stage=ner) — no swallow."""
    from app.triage.ner import NerUnavailable
    from app.triage.service import triage_document

    with (
        patch("app.triage.service.extract_entities", side_effect=NerUnavailable("ner down")),
        patch("app.triage.service._log") as mock_log,
    ):
        bound = mock_log.bind.return_value
        with pytest.raises(NerUnavailable):
            await triage_document(
                session=AsyncMock(),
                document_id=1,
                client_id=1,
                document_text="Patient text.",
                source_reliability="peer_reviewed",
                watchlist_drugs=["ibuprofen"],
                custom_keywords=[],
                ms_client=AsyncMock(),
                settings=MagicMock(),
                dispatcher=AsyncMock(),
            )

    # The NER outage is surfaced as an operator alert (stage=ner), not silently swallowed.
    assert any(
        c.args and c.args[0] == "triage.operator_alert" and c.kwargs.get("stage") == "ner"
        for c in bound.error.call_args_list
    )


# ---------------------------------------------------------------------------
# Degraded marking — a triage failure records a durable per-document marker, and
# the cycle completes 'degraded', never clean (Constitution III).
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _acm(value=None):
    """Minimal async context manager yielding `value` (stands in for session_factory/begin)."""
    yield value


@pytest.mark.asyncio
async def test_mark_completed_records_degraded_reason():
    """mark_completed(degraded_reason=...) records it while status stays 'completed'.

    The partial batch report still ships (status completed), but degraded_reason != NULL means
    the run must not be read as a clean 'all clear'.
    """
    from app.scheduling.models import WatchlistCycle
    from app.scheduling.service import CycleService

    cycle = WatchlistCycle()
    session = AsyncMock()
    session.get = AsyncMock(return_value=cycle)

    result = await CycleService.mark_completed(session, 1, degraded_reason="triage_failed")

    assert result is cycle
    assert cycle.status == "completed"
    assert cycle.current_stage == "done"
    assert cycle.degraded_reason == "triage_failed"


@pytest.mark.asyncio
async def test_mark_triage_degraded_sets_marker():
    """A triage failure writes triage_failed_at + a PII-free reason code (no silent swallow)."""
    from types import SimpleNamespace

    from app.embedding import triage_trigger
    from app.triage.ner import NerUnavailable

    state = SimpleNamespace(triage_failed_at=None, triage_error=None)
    document = SimpleNamespace(id=99)

    session = MagicMock()
    session.begin = lambda: _acm(None)

    def session_factory():
        return _acm(session)

    with patch(
        "app.embedding.service.IndexBuildService.get_or_create_index_state",
        new=AsyncMock(return_value=state),
    ):
        await triage_trigger._mark_triage_degraded(
            session_factory, document, client_id=7, exc=NerUnavailable("ner down")
        )

    assert state.triage_failed_at is not None
    assert state.triage_error == "ner_unavailable"


# ---------------------------------------------------------------------------
# Orphaned-expedited (2B) — the expedited enqueue is isolated per finding: one
# enqueue failure is surfaced and does NOT skip the others (the sweep re-enqueues).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueue_expedited_drafts_isolates_failures():
    """An enqueue failure for one expedited finding is surfaced and does not skip the others."""
    from types import SimpleNamespace

    from app.embedding import triage_trigger
    from app.triage.enums import Bucket

    outcomes = [
        SimpleNamespace(created=True, finding_id=1, bucket=Bucket.EMERGENCY),
        SimpleNamespace(created=True, finding_id=2, bucket=Bucket.URGENT),
        SimpleNamespace(created=True, finding_id=3, bucket=Bucket.MINOR),  # not expedited; skipped
    ]

    attempted: list[int] = []

    async def fake_enqueue(task, *, job_id, app_state, finding_id, revision):
        attempted.append(finding_id)
        if finding_id == 1:
            raise RuntimeError("redis down")

    with (
        patch("app.jobs.enqueue.enqueue", new=fake_enqueue),
        patch("app.embedding.triage_trigger._log") as mock_log,
    ):
        await triage_trigger._enqueue_expedited_drafts(outcomes, app_state=object(), client_id=7)

    # Finding 1 failed but did NOT abort finding 2; finding 3 (MINOR) is not expedited.
    assert attempted == [1, 2]
    # The failed enqueue surfaced an operator alert (stage=expedited_enqueue).
    assert any(
        c.args
        and c.args[0] == "triage.operator_alert"
        and c.kwargs.get("stage") == "expedited_enqueue"
        and c.kwargs.get("finding_id") == 1
        for c in mock_log.error.call_args_list
    )


# ---------------------------------------------------------------------------
# Classifier-version attribution — a normal classification stamps the finding's
# audit event with the classifier SHA-256 (an outage stamps None; see above).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finding_event_carries_classifier_version():
    """A normal classification stamps the finding's audit event with the classifier SHA-256."""
    from app.triage.service import _triage_one

    ms_client = AsyncMock()
    ms_client.classify.return_value = [
        {"confidence": 0.93, "is_adverse": True, "model_version": {"sha256": "clf-sha-777"}}
    ]

    session = AsyncMock()
    dispatcher = AsyncMock()
    settings = MagicMock()
    settings.triage_confidence_threshold = 0.70
    log = MagicMock()

    with patch(
        "app.triage.service.upsert_finding",
        new=AsyncMock(return_value=(55, True)),
    ):
        await _triage_one(
            session=session,
            document_id=1,
            client_id=1,
            drug="ibuprofen",
            reaction="anaphylaxis",
            document_text="Patient suffered anaphylaxis after ibuprofen.",
            source_reliability="peer_reviewed",
            custom_keywords=[],
            ms_client=ms_client,
            settings=settings,
            dispatcher=dispatcher,
            log=log,
        )

    dispatcher.dispatch.assert_awaited_once()
    event = dispatcher.dispatch.call_args.args[0]
    assert event.classifier_version == "clf-sha-777"


@pytest.mark.asyncio
async def test_mark_triage_succeeded_sets_triaged_and_clears_degraded():
    """A successful triage records triaged_at and clears any prior degraded marker.

    This is what lets the staleness sweep avoid re-triaging a legitimately-zero-finding document.
    """
    from types import SimpleNamespace

    from app.embedding import triage_trigger

    state = SimpleNamespace(
        triaged_at=None, triage_failed_at="2026-01-01", triage_error="ner_unavailable"
    )
    document = SimpleNamespace(id=5)

    session = MagicMock()
    session.begin = lambda: _acm(None)

    def session_factory():
        return _acm(session)

    with patch(
        "app.embedding.service.IndexBuildService.get_or_create_index_state",
        new=AsyncMock(return_value=state),
    ):
        await triage_trigger._mark_triage_succeeded(session_factory, document, client_id=1)

    assert state.triaged_at is not None
    assert state.triage_failed_at is None
    assert state.triage_error is None


# ---------------------------------------------------------------------------
# Backstop sweep — REMEDIATES (re-enqueues) untriaged docs + orphaned expedited
# findings, with deterministic idempotent job_ids (not just a log warning).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_triage_sweep_remediates_untriaged_and_orphans():
    """The sweep re-enqueues a re-triage per untriaged doc and a draft per orphaned expedited."""
    from types import SimpleNamespace

    from app.triage import sweep as sweep_mod

    enqueued: list[tuple[str, str, dict]] = []

    async def fake_enqueue(name, *, job_id, app_state, **kwargs):
        enqueued.append((name, job_id, kwargs))

    wc = SimpleNamespace(session_factory=lambda: _acm(MagicMock()))

    with (
        patch.object(
            sweep_mod,
            "find_untriaged_documents",
            new=AsyncMock(return_value=[(10, 1), (11, 2)]),
        ),
        patch.object(
            sweep_mod,
            "find_orphaned_expedited",
            new=AsyncMock(return_value=[(99, 1)]),
        ),
        patch("app.jobs.enqueue.enqueue", new=fake_enqueue),
    ):
        result = await sweep_mod.run_triage_sweep(wc)

    assert result == {"retriaged": 2, "reexpedited": 1}
    names = [e[0] for e in enqueued]
    assert names.count("task_retriage_document") == 2
    assert names.count("task_expedited") == 1
    # Deterministic, idempotent job_ids (a sweep overlapping an in-flight job is a no-op).
    job_ids = {e[1] for e in enqueued}
    assert {"retriage:10", "retriage:11", "expedited:99:0"} <= job_ids


# ---------------------------------------------------------------------------
# Operator-alert surfacing — handled triage failures reach Sentry (not just stdout),
# so a silent classifier/NER outage pages instead of passing unnoticed (audit A2).
# ---------------------------------------------------------------------------


def test_capture_operator_alert_sends_error_message():
    """capture_operator_alert sends an error-level Sentry message (PII-free tags)."""
    from app.observability import sentry as sentry_mod

    with patch.object(sentry_mod.sentry_sdk, "capture_message") as cap:
        sentry_mod.capture_operator_alert(
            "triage.operator_alert", stage="classify", client_id=7, document_id=None
        )

    cap.assert_called_once()
    assert cap.call_args.args[0] == "triage.operator_alert"
    assert cap.call_args.kwargs.get("level") == "error"
