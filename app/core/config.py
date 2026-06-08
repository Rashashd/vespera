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
    auth_token_ttl_seconds: int = 1800  # access-token lifetime ~30 min (spec 2 FR-001)

    # --- Secret fields: initialized empty, populated from Vault at startup ---
    database_url: str = ""
    redis_url: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    modelserver_token: str = ""
    guardrails_token: str = ""
    auth_jwt_secret: str = ""  # JWT signing secret (spec 2 FR-015); from Vault, never .env
    # Bootstrap admin (spec 2 FR-011): consumed only by scripts/seed_admin.py, from Vault.
    bootstrap_admin_email: str = ""
    bootstrap_admin_password: str = ""
    bootstrap_admin_client_id: int = 1

    # --- Ingestion: optional source credentials (NOT in _REQUIRED_SECRETS — D7) ---
    pubmed_api_key: str = ""  # NCBI E-utilities API key; empty ⇒ keyless (10 req/s limit)
    openfda_api_key: str = ""  # openFDA API key; empty ⇒ keyless (240 req/min limit)

    # --- Ingestion: non-secret configuration ---
    ncbi_tool_email: str = "pantera@example.com"  # sent to NCBI as courtesy identification
    ingestion_initial_lookback_days: int = 365  # first-run lookback window (D9)
    ingestion_per_source_cap: int = 200  # max records fetched per source per run (D9)


def get_settings() -> Settings:
    """Build a Settings instance from the environment (Vault bootstrap only)."""
    return Settings()
