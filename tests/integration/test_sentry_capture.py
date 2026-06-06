"""Sentry wiring test (US3 / SC-005): enabled by DSN, configured without PII."""

import sentry_sdk

from app.core.config import Settings
from app.observability.sentry import init_sentry


def test_sentry_disabled_without_dsn():
    """Without a DSN, Sentry stays disabled."""
    assert init_sentry(Settings(sentry_dsn="")) is False


def test_sentry_enabled_and_no_pii():
    """With a DSN, Sentry is enabled and send_default_pii is False."""
    enabled = init_sentry(Settings(sentry_dsn="https://public@o0.ingest.example.com/1"))
    assert enabled
    assert sentry_sdk.get_client().options["send_default_pii"] is False
