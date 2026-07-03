"""CORS prod-safety (Cluster 4 / A5): check_cors_configuration must REFUSE prod boot when
cors_allow_origins is unset (the dev default), wildcard-open, or a localhost origin — so the dev
origin can never silently ship and CORS can never silently open in production. Non-prod keeps the
permissive dev default."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.startup import check_cors_configuration


def _settings(**overrides) -> SimpleNamespace:
    base = {"environment": "production", "cors_allow_origins": ["https://app.vespera.io"]}
    base.update(overrides)
    return SimpleNamespace(**base)


def test_production_with_real_origin_boots():
    """Prod + a real HTTPS SPA origin → no raise (happy path)."""
    check_cors_configuration(_settings())


@pytest.mark.parametrize("env", ["development", "test", "TEST", " Development "])
def test_non_prod_keeps_dev_default(env):
    """Dev/test keep the permissive localhost default without raising."""
    check_cors_configuration(
        _settings(environment=env, cors_allow_origins=["http://localhost:5173"])
    )
    check_cors_configuration(_settings(environment=env, cors_allow_origins=[]))
    check_cors_configuration(_settings(environment=env, cors_allow_origins=["*"]))


def test_production_refuses_default_dev_origin():
    """Prod still carrying the default dev origin (forgot to override) → refuse boot."""
    with pytest.raises(RuntimeError, match="development or wildcard origin"):
        check_cors_configuration(_settings(cors_allow_origins=["http://localhost:5173"]))


@pytest.mark.parametrize(
    "origin", ["http://localhost:5173", "http://127.0.0.1:3000", "http://[::1]:8080"]
)
def test_production_refuses_any_loopback_origin(origin):
    """Any localhost/loopback origin in prod → refuse boot (dev config leaked)."""
    with pytest.raises(RuntimeError, match="development or wildcard origin"):
        check_cors_configuration(_settings(cors_allow_origins=[origin]))


def test_production_refuses_wildcard():
    """A wide-open `*` origin in prod → refuse boot (CORS silently open to any site)."""
    with pytest.raises(RuntimeError, match="development or wildcard origin"):
        check_cors_configuration(_settings(cors_allow_origins=["*"]))


def test_production_refuses_wildcard_mixed_with_real():
    """`*` alongside a real origin is still refused (the wildcard dominates)."""
    with pytest.raises(RuntimeError, match="development or wildcard origin"):
        check_cors_configuration(_settings(cors_allow_origins=["https://app.vespera.io", "*"]))


def test_production_refuses_empty_origins():
    """Empty origins in prod → refuse boot (nothing configured; SPA would break)."""
    with pytest.raises(RuntimeError, match="cors_allow_origins is empty"):
        check_cors_configuration(_settings(cors_allow_origins=[]))
