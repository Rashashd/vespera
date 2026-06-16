"""LangSmith tracing setup; OFF by default and PII-safe at every traced call site (FR-023/032/035).

Tracing is gated behind an explicit ``tracing_enabled`` switch AND a configured key — empty or
disabled is a no-op so the app always boots. Two controls keep traces PII-free:
  - Triage: ``traced_llm_call`` records only non-PII metadata (client_id, max_tokens) and drops
    the response body.
  - Drafting agent: LangChain auto-traces the messages it sends, but those messages are REDACTED
    at egress (Presidio; ``app/agent/graph.py`` redacts Human/Tool content before
    ``chat_model.ainvoke``), so the captured trace carries only redacted content (FR-024 —
    "redaction is the control"); the output is derived from redacted input and is also guarded.
Tracing still defaults OFF; flip ``tracing_enabled`` on only in non-prod to verify (US4/SC-007).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

import structlog

from app.core.config import Settings

_log = structlog.get_logger(__name__)

# Only these argument names are safe to record in a trace — everything else (document text, prompts,
# Settings/secrets) is dropped.
_SAFE_INPUT_KEYS = ("client_id", "max_tokens")


def configure_tracing(settings: Settings) -> None:
    """Enable LangSmith tracing only when explicitly switched on AND a key is present (FR-032).

    With Presidio egress redaction in place (spec 12), the agent trace carries redacted content
    (FR-024). Tracing still defaults OFF; the note records that redaction is the control.
    """
    if not (settings.tracing_enabled and settings.langsmith_api_key):
        return
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project
    _log.info(
        "observability.tracing.enabled",
        project=settings.langsmith_project,
        note=(
            "LangSmith tracing is ON. Agent messages are Presidio-redacted at egress before the "
            "model call (redaction is the control, FR-024); verify a sample trace is PII-free."
        ),
    )


def traced_llm_call(func: Callable[..., Any]) -> Callable[..., Any]:
    """Trace an LLM call site, redacting inputs/outputs to non-PII metadata (FR-035).

    Records only safe call metadata (client_id, max_tokens) — never the document text, prompts,
    settings, or secrets — and drops the response body. No-op when langsmith is unavailable.
    """
    try:
        from langsmith import traceable as _traceable
    except Exception:
        return func

    def _redact_inputs(inputs: dict) -> dict:
        return {k: inputs[k] for k in _SAFE_INPUT_KEYS if k in inputs}

    def _redact_outputs(_output: Any) -> dict:
        return {"redacted": True}

    return _traceable(
        name="triage_llm_call",
        process_inputs=_redact_inputs,
        process_outputs=_redact_outputs,
    )(func)
