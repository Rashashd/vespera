"""Unit tests for the log redaction processor (FR-008 / SC-003)."""

from app.observability.logging import _REDACTED, _is_sensitive, _redact_processor


def test_exact_secret_and_pii_keys_are_sensitive():
    """Known secret/PII key names are flagged for redaction."""
    for key in ("database_url", "redis_url", "authorization", "patient_name", "ssn", "email"):
        assert _is_sensitive(key)


def test_substring_keys_are_sensitive():
    """Keys containing a secret substring (api_key/token/secret/password) are flagged."""
    keys = ("anthropic_api_key", "openai_api_key", "vault_token", "guardrails_token", "PASSWORD")
    for key in keys:
        assert _is_sensitive(key)


def test_benign_keys_are_not_sensitive():
    """Ordinary keys are not redacted."""
    for key in ("client_id", "finding_id", "status", "provider", "model"):
        assert not _is_sensitive(key)


def test_processor_redacts_values():
    """The processor replaces sensitive values and leaves benign ones intact."""
    event = {"client_id": 7, "anthropic_api_key": "sk-secret", "database_url": "postgres://u:p@h/db"}
    out = _redact_processor(None, "info", event)
    assert out["client_id"] == 7
    assert out["anthropic_api_key"] == _REDACTED
    assert out["database_url"] == _REDACTED
