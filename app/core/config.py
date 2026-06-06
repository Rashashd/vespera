"""Single validated settings object (non-secret config + in-memory secret fields)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration; unknown fields are rejected (FR-017)."""

    model_config = SettingsConfigDict(extra="forbid", env_file=None)

    # --- Vault bootstrap (the ONLY values read from the environment) ---
    vault_addr: str = "http://vault:8200"
    vault_token: str = "root"  # dev-mode convention; production holds only this token
    vault_secret_path: str = "pantera/secrets"

    # --- Non-secret configuration (safe as defaults) ---
    anthropic_model: str = "claude-3-5-sonnet-20241022"  # pinned
    openai_model: str = "gpt-4o-2024-08-06"  # pinned
    preferred_provider: str = "anthropic"
    log_level: str = "INFO"
    sentry_dsn: str = ""  # non-secret DSN; empty disables Sentry

    # --- Secret fields: initialized empty, populated from Vault at startup ---
    database_url: str = ""
    redis_url: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    modelserver_token: str = ""
    guardrails_token: str = ""


def get_settings() -> Settings:
    """Build a Settings instance from the environment (Vault bootstrap only)."""
    return Settings()
