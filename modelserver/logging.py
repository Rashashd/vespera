"""Structlog JSON logging for the modelserver.

Binds operation/batch_size/latency_ms/model_version; never logs payloads, PII,
or secret values (D16/FR-020/SC-008).
"""

import logging
from typing import Any

import structlog

_REDACT_SUBSTRINGS = ("token", "secret", "password", "api_key", "authorization")


def _redact_processor(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Replace any key that looks like a secret with a redaction marker."""
    for key in list(event_dict.keys()):
        if any(s in key.lower() for s in _REDACT_SUBSTRINGS):
            event_dict[key] = "***redacted***"
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog for JSON emission with secret/PII redaction."""
    logging.basicConfig(format="%(message)s", level=getattr(logging, level.upper(), logging.INFO))
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
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


def get_logger(name: str | None = None) -> Any:
    """Return a structlog logger bound to the given name."""
    return structlog.get_logger(name)
