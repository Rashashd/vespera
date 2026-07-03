"""Fail-closed security boundary (Cluster 4 / M3 / A4): check_security_boundary must REFUSE boot
when a mandatory security toggle (guardrails/redaction) is disabled for ANY environment except an
explicit `development`/`test` — including an unset/unknown/misspelled ENVIRONMENT (default
"production"). A prod deploy that forgets ENVIRONMENT can never silently drop the boundary."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.core.startup import check_security_boundary


def _settings(**overrides) -> SimpleNamespace:
    """Settings-like object; toggles default ON (as in prod). Override per test."""
    base = {"environment": "production", "guardrails_enabled": True, "redaction_enabled": True}
    base.update(overrides)
    return SimpleNamespace(**base)


def test_unset_environment_resolves_to_production(monkeypatch):
    """Fail-closed default: with ENVIRONMENT absent from the env, Settings resolves 'production'.

    (conftest sets ENVIRONMENT=development for the suite, so we delete it to test the real unset
    case — a prod deploy that never sets ENVIRONMENT.)
    """
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    assert Settings().environment == "production"


def test_production_with_toggles_on_boots():
    """Prod + both toggles enabled (the shipped default) → no raise (happy path)."""
    check_security_boundary(_settings())


@pytest.mark.parametrize("env", ["development", "test", "TEST", " Development ", "development\n"])
def test_dev_and_test_may_disable_toggles(env):
    """Only an explicit development/test env (case/space-insensitive) may disable the boundary."""
    check_security_boundary(_settings(environment=env, guardrails_enabled=False))
    check_security_boundary(_settings(environment=env, redaction_enabled=False))


def test_production_refuses_disabled_guardrails():
    """Prod + guardrails disabled → refuse boot."""
    with pytest.raises(RuntimeError, match="guardrails_enabled"):
        check_security_boundary(_settings(guardrails_enabled=False))


def test_production_refuses_disabled_redaction():
    """Prod + redaction disabled → refuse boot."""
    with pytest.raises(RuntimeError, match="redaction_enabled"):
        check_security_boundary(_settings(redaction_enabled=False))


@pytest.mark.parametrize("env", ["", "production", "staging", "prod", "dev", "develop", "unknown"])
def test_non_dev_environments_fail_closed_with_toggle_off(env):
    """Unset/unknown/staging/typo'd env with a disabled toggle refuses boot (the M3/A4 hole).

    Includes "" (empty) and "dev"/"develop" (near-misses that are NOT the exact dev/test opt-in),
    proving the boundary only bypasses on an explicit development/test value.
    """
    with pytest.raises(RuntimeError, match="cannot be disabled outside a development/test"):
        check_security_boundary(
            _settings(environment=env, guardrails_enabled=False, redaction_enabled=False)
        )
