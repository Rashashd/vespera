"""Fail-safe and failure-matrix unit tests (US4, FR-018/FR-019, SC-007)."""

from __future__ import annotations

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

    verdict, confidence, path = await resolve_adverse(
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

    verdict, confidence, path = await resolve_adverse(
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
# Classifier (ModelserverError) failure — service._triage_one must return None
# and emit triage.operator_alert (stage=classify).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classifier_error_returns_none_and_logs_alert():
    """ModelserverError → _triage_one returns None + operator_alert logged (stage=classify)."""
    from app.triage.service import _triage_one

    ms_client = AsyncMock()
    ms_client.classify.side_effect = ModelserverError("modelserver unreachable")

    session = AsyncMock()
    dispatcher = AsyncMock()
    settings = MagicMock()
    settings.triage_confidence_threshold = 0.70
    log = MagicMock()

    result = await _triage_one(
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

    assert result is None
    log.error.assert_called_once()
    call_kwargs = log.error.call_args
    assert call_kwargs[0][0] == "triage.operator_alert"
    assert call_kwargs[1]["stage"] == "classify"


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
    ms_client.classify.return_value = [{"confidence": 0.92, "is_adverse": True}]

    settings = MagicMock()
    settings.triage_confidence_threshold = 0.70

    llm_called = False

    async def should_not_be_called(text, reliability):
        nonlocal llm_called
        llm_called = True
        return True

    verdict, confidence, path = await resolve_adverse(
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
    assert llm_called is False
