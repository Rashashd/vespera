"""Vault secret loading for the guardrails sidecar (refuses boot without its credential)."""

from __future__ import annotations

import hvac

from guardrails.core.config import GuardrailsConfig
from guardrails.core.logging import get_logger

_log = get_logger(__name__)


def load_guardrails_token(config: GuardrailsConfig) -> str:
    """Return the service token; use config/env if set, otherwise load from Vault.

    Raises RuntimeError to abort boot if the token is empty after all attempts.
    """
    if config.guardrails_token:
        _log.info("guardrails.token.loaded", source="config")
        return config.guardrails_token

    client = hvac.Client(url=config.vault_addr, token=config.vault_token)
    try:
        authenticated = client.is_authenticated()
    except Exception as exc:
        raise RuntimeError(f"Cannot reach Vault at {config.vault_addr}: {exc}") from exc
    if not authenticated:
        raise RuntimeError("Cannot authenticate with Vault")

    try:
        data = client.secrets.kv.v2.read_secret_version(
            path=config.vault_secret_path, raise_on_deleted_version=True
        )["data"]["data"]
    except Exception as exc:
        raise RuntimeError(f"Failed to read secrets from Vault: {exc}") from exc

    token = data.get("guardrails_token", "")
    if not token:
        raise RuntimeError("guardrails_token is required but missing from Vault")

    _log.info("guardrails.token.loaded", source="vault")
    return token
