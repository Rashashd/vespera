"""Sentry initialization for unhandled-exception capture (no PII)."""

from typing import Any

import sentry_sdk

from app.core.config import Settings


def init_sentry(settings: Settings) -> bool:
    """Initialize Sentry when a DSN is configured; return True if enabled (FR-009/SC-005)."""
    if not settings.sentry_dsn:
        return False
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        send_default_pii=False,
        traces_sample_rate=0.0,
    )
    return True


def capture_operator_alert(message: str, **context: Any) -> None:
    """Surface a handled triage operator-alert to Sentry (PII-free context only).

    Classifier/NER outages, degraded-marker failures, and sweep remediations are logged-and-
    returned — no exception propagates — so Sentry's ASGI integration never sees them and a silent
    triage outage would otherwise only hit stdout (audit finding A2). Capturing them as error-level
    messages makes them page/alert. A no-op when Sentry is not initialized (no DSN).

    Context values MUST be PII-free (IDs, stage names, reason/error CODES) — never document text.
    """
    with sentry_sdk.new_scope() as scope:
        for key, value in context.items():
            if value is not None:
                scope.set_tag(key, str(value))
        sentry_sdk.capture_message(message, level="error")
