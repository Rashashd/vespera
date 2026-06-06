"""Unit tests for the Settings configuration object (FR-017 / SC-009)."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_rejects_unknown_field():
    """An unknown/invalid config field must be rejected (extra='forbid')."""
    with pytest.raises(ValidationError):
        Settings(unexpected_field="boom")


def test_secret_fields_default_empty():
    """Secret fields declare an empty default; they are populated from Vault at startup.

    Asserts the declared default (not an instance) so ambient env vars like a real
    DATABASE_URL don't make this test flaky.
    """
    for field in ("database_url", "redis_url", "anthropic_api_key", "openai_api_key"):
        assert Settings.model_fields[field].default == ""


def test_pinned_models_present():
    """Non-secret pinned model ids have sensible defaults."""
    settings = Settings()
    assert settings.anthropic_model
    assert settings.openai_model
    assert settings.preferred_provider == "anthropic"
