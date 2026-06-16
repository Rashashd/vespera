"""Pydantic-settings for the guardrails sidecar — no secrets on disk (mirrors modelserver)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class GuardrailsConfig(BaseSettings):
    """Guardrails sidecar configuration; unknown fields rejected (extra='forbid')."""

    model_config = SettingsConfigDict(extra="forbid", env_file=None)

    vault_addr: str = "http://vault:8200"
    vault_token: str = "root"
    vault_secret_path: str = "pantera/secrets"

    log_level: str = "INFO"

    # Populated from Vault at startup; env-var override allowed for tests.
    guardrails_token: str = ""


def get_config() -> GuardrailsConfig:
    """Build a GuardrailsConfig from the environment."""
    return GuardrailsConfig()
