"""Structured JSON logging with tenant binding and secret/PII redaction."""

import logging
from typing import Any

import structlog

# Exact PII/secret key names that must never be emitted in logs.
_REDACT_KEYS = frozenset(
    {
        "database_url",
        "redis_url",
        "authorization",
        "patient_name",
        "ssn",
        "email",
    }
)

# Any key containing one of these substrings is redacted (catches *_api_key, *_token, etc.).
_REDACT_SUBSTRINGS = ("api_key", "secret", "token", "password")

_REDACTED = "***redacted***"


def _is_sensitive(key: str) -> bool:
    """True if a log key names a secret or PII value that must be redacted."""
    lowered = key.lower()
    return lowered in _REDACT_KEYS or any(s in lowered for s in _REDACT_SUBSTRINGS)


def _redact_processor(
    _logger: Any, _method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Replace the value of any secret/PII-named key with a redaction marker."""
    for key in list(event_dict.keys()):
        if _is_sensitive(key):
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
