"""Unit tests for modelserver startup: token loading and artifact validation.

Vault path is tested with a mock hvac client to avoid needing a real Vault container.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from modelserver.core.config import ModelserverConfig
from modelserver.core.startup import load_modelserver_token


def _config(**kwargs) -> ModelserverConfig:
    defaults = {
        "vault_addr": "http://vault:8200",
        "vault_token": "root",
        "vault_secret_path": "pantera/secrets",
        "modelserver_token": "",
    }
    defaults.update(kwargs)
    return ModelserverConfig(**defaults)


# ---------------------------------------------------------------------------
# Env/config bypass (no Vault needed)
# ---------------------------------------------------------------------------


def test_load_token_from_config():
    cfg = _config(modelserver_token="direct-token")
    assert load_modelserver_token(cfg) == "direct-token"


# ---------------------------------------------------------------------------
# Vault path (mock hvac)
# ---------------------------------------------------------------------------


def test_load_token_from_vault():
    mock_client = MagicMock()
    mock_client.is_authenticated.return_value = True
    mock_client.secrets.kv.v2.read_secret_version.return_value = {
        "data": {"data": {"modelserver_token": "vault-token"}}
    }
    with patch("modelserver.core.startup.hvac.Client", return_value=mock_client):
        token = load_modelserver_token(_config())
    assert token == "vault-token"


def test_vault_unreachable_raises():
    mock_client = MagicMock()
    mock_client.is_authenticated.side_effect = Exception("connection refused")
    with patch("modelserver.core.startup.hvac.Client", return_value=mock_client):
        with pytest.raises(RuntimeError, match="Cannot reach Vault"):
            load_modelserver_token(_config())


def test_vault_unauthenticated_raises():
    mock_client = MagicMock()
    mock_client.is_authenticated.return_value = False
    with patch("modelserver.core.startup.hvac.Client", return_value=mock_client):
        with pytest.raises(RuntimeError, match="Cannot authenticate"):
            load_modelserver_token(_config())


def test_vault_missing_token_key_raises():
    mock_client = MagicMock()
    mock_client.is_authenticated.return_value = True
    mock_client.secrets.kv.v2.read_secret_version.return_value = {
        "data": {"data": {}}  # no modelserver_token key
    }
    with patch("modelserver.core.startup.hvac.Client", return_value=mock_client):
        with pytest.raises(RuntimeError, match="modelserver_token is required"):
            load_modelserver_token(_config())


def test_vault_read_failure_raises():
    mock_client = MagicMock()
    mock_client.is_authenticated.return_value = True
    mock_client.secrets.kv.v2.read_secret_version.side_effect = Exception("read failed")
    with patch("modelserver.core.startup.hvac.Client", return_value=mock_client):
        with pytest.raises(RuntimeError, match="Failed to read secrets"):
            load_modelserver_token(_config())
