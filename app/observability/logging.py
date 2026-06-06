"""Structured JSON logging with tenant binding and secret/PII redaction."""

import logging
from typing import Any

import structlog

# Keys whose values must never be emitted in logs (secrets + obvious PII).
_REDACT_KEYS = frozenset(
    {
        "anthropic_api_key",
        "openai_api_key",
        "modelserver_token",
        "guardrails_token",
        "vault_token",
        "database_url",
        "redis_url",
        "password",
        "token",
        "secret",
        "authorization",
        "api_key",
        "patient_name",
        "ssn",
        "email",
    }
)

_REDACTED = "***redacted***"


def _redact_processor(
    _logger: Any, _method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Replace the value of any secret/PII-named key with a redaction marker."""
    for key in list(event_dict.keys()):
        if key.lower() in _REDACT_KEYS:
            event_dict[key] = _REDACTED
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog to emit redacted JSON; bind client_id/finding_id via contextvars."""
    logging.basicConfig(format="%(message)s", level=getattr(logging, level.upper(), logging.INFO))
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,  # client_id / finding_id when bound
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _redact_processor,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )


def bind_context(**kwargs: Any) -> None:
    """Bind request-scoped context (e.g., client_id, finding_id) onto every later log line."""
    structlog.contextvars.bind_contextvars(**kwargs)


def get_logger(name: str | None = None) -> Any:
    """Return a structlog logger."""
    return structlog.get_logger(name)
