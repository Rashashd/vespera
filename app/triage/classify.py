"""Modelserver /classify wrapper and three-stage confidence-threshold decision (FR-002)."""

from __future__ import annotations

import structlog

from app.core.config import Settings
from app.infra.modelserver_client import ModelserverClient

_log = structlog.get_logger(__name__)


async def classify_text(
    text: str,
    ms_client: ModelserverClient,
) -> tuple[float, bool]:
    """Call POST /classify for a single text; return (confidence, is_adverse).

    Uses raw confidence from the modelserver response; is_adverse reflects the
    modelserver's internal 0.5 cutoff — callers re-threshold using settings.
    """
    results = await ms_client.classify([text])
    result = results[0]
    return float(result["confidence"]), bool(result["is_adverse"])


async def resolve_adverse(
    text: str,
    ms_client: ModelserverClient,
    settings: Settings,
    llm_resolve_fn,  # async (text: str, source_reliability: str) -> bool
    source_reliability: str,
    client_id: int,
    document_id: int,
) -> tuple[bool, float | None, str]:
    """Three-stage classify decision (FR-002).

    Returns (verdict, model_confidence, resolution_path) where:
      - verdict=True → adverse event (YES path)
      - resolution_path ∈ {'model', 'llm', 'escalated'}
      - model_confidence is None when verdict came from LLM/escalation
    """
    log = _log.bind(client_id=client_id, document_id=document_id)
    confidence, is_adverse = await classify_text(text, ms_client)

    if confidence >= settings.triage_confidence_threshold:
        log.info("triage.classify.model", confidence=confidence, verdict=is_adverse)
        return is_adverse, confidence, "model"

    log.info("triage.classify.low_confidence", confidence=confidence)
    try:
        verdict = await llm_resolve_fn(text, source_reliability)
        log.info("triage.classify.llm", verdict=verdict)
        return verdict, None, "llm"
    except Exception as exc:
        log.warning("triage.classify.escalated", reason=str(exc))
        return True, None, "escalated"
