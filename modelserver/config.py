"""Pydantic-settings for the modelserver — no secrets on disk (D5/FR-016)."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelserverConfig(BaseSettings):
    """Modelserver configuration; unknown fields rejected (extra='forbid')."""

    model_config = SettingsConfigDict(extra="forbid", env_file=None)

    vault_addr: str = "http://vault:8200"
    vault_token: str = "root"
    vault_secret_path: str = "pantera/secrets"

    model_dir: Path = Path("modelserver/models")
    max_batch: int = 128
    max_tokens: int = 512
    log_level: str = "INFO"

    # Populated from Vault at startup; env-var override allowed for tests
    modelserver_token: str = ""


def get_config() -> ModelserverConfig:
    """Build a ModelserverConfig from the environment."""
    return ModelserverConfig()
