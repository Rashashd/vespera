"""Sentry initialization for unhandled-exception capture (no PII)."""

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
