"""Unit tests for configure_tracing (US8/FR-032): sets LANGCHAIN_* only when enabled + keyed."""

import os

from app.core.config import Settings
from app.observability.tracing import configure_tracing

_VARS = ("LANGCHAIN_TRACING_V2", "LANGCHAIN_API_KEY", "LANGCHAIN_PROJECT")


def _settings(**overrides) -> Settings:
    base = {"tracing_enabled": False, "langsmith_api_key": "", "langsmith_project": "pantera"}
    base.update(overrides)
    return Settings(**base)


class TestConfigureTracing:
    def test_enabled_with_key_sets_env(self, monkeypatch):
        # Pre-touch so monkeypatch owns these vars and restores them on teardown.
        for v in _VARS:
            monkeypatch.setenv(v, "sentinel")
        configure_tracing(
            _settings(tracing_enabled=True, langsmith_api_key="ls-secret", langsmith_project="proj")
        )
        assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
        assert os.environ["LANGCHAIN_API_KEY"] == "ls-secret"
        assert os.environ["LANGCHAIN_PROJECT"] == "proj"

    def test_disabled_is_noop(self, monkeypatch):
        for v in _VARS:
            monkeypatch.delenv(v, raising=False)
        configure_tracing(_settings(tracing_enabled=False, langsmith_api_key="ls-secret"))
        assert "LANGCHAIN_TRACING_V2" not in os.environ

    def test_empty_key_is_noop(self, monkeypatch):
        for v in _VARS:
            monkeypatch.delenv(v, raising=False)
        configure_tracing(_settings(tracing_enabled=True, langsmith_api_key=""))
        assert "LANGCHAIN_TRACING_V2" not in os.environ
