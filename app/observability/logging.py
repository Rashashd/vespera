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


# Lazy handle to the spaCy-free value scrubber (secrets + structured identifiers). Imported on
# first use so the redaction package (and Presidio) stays out of the early logging import chain.
_scrub: Any = None


def _get_scrub() -> Any:
    """Return the value scrubber, importing it lazily; degrade to identity if unavailable."""
    global _scrub
    if _scrub is None:
        try:
            from app.redaction.recognizers import scrub_text

            _scrub = scrub_text
        except Exception:  # noqa: BLE001 - logging must never fail to import
            _scrub = lambda value: value  # noqa: E731
    return _scrub


def _redact_processor(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Redact secret/PII-named keys, and scrub secrets/identifiers from string values (FR-009)."""
    scrub = _get_scrub()
    for key in list(event_dict.keys()):
        if _is_sensitive(key):
            event_dict[key] = _REDACTED
        elif isinstance(event_dict[key], str):
            event_dict[key] = scrub(event_dict[key])
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
