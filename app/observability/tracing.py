"""LangSmith tracing setup; OFF by default and PII-safe at the triage call site (FR-032/035).

Tracing is gated behind an explicit ``tracing_enabled`` switch AND a configured key — empty/disabled
is a no-op so the app always boots. When enabled, the triage LLM call is traced with its inputs and
outputs REDACTED to non-PII metadata only (no document text, prompts, or secrets), so traces never
contain patient PII even before the Presidio redaction sweep (spec 12) lands. The LangChain drafting
agent auto-traces full content when tracing is on (a spec-12 redaction concern), so tracing MUST
remain disabled in production until Presidio exists (see the warning emitted on enable).
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

    Emits a loud warning that traces may carry unredacted clinical text until Presidio (spec 12).
    """
    if not (settings.tracing_enabled and settings.langsmith_api_key):
        return
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project
    _log.warning(
        "observability.tracing.enabled",
        project=settings.langsmith_project,
        caution=(
            "LangSmith tracing is ON. The drafting-agent path traces full content; until the "
            "Presidio redaction sweep (spec 12) exists, traces may contain unredacted clinical "
            "text — do NOT enable in production with real patient data."
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
