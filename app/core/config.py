"""Single validated settings object (non-secret config + in-memory secret fields)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration; unknown fields are rejected (FR-017)."""

    model_config = SettingsConfigDict(extra="forbid", env_file=None)

    # --- Vault bootstrap (the ONLY values read from the environment) ---
    vault_addr: str = "http://vault:8200"
    vault_token: str = "root"  # dev-mode convention; production holds only this token
    vault_secret_path: str = "pantera/secrets"

    # --- Deployment environment (spec 12) ---
    # Drives production-only safety guards (e.g. the guardrails/redaction kill-switch guard,
    # T002a). Override with env ENVIRONMENT=production on real deployments. There is no other
    # production signal in the codebase; key prod-only behaviour off this single field.
    environment: str = "development"

    # --- Non-secret configuration (safe as defaults) ---
    anthropic_model: str = "claude-3-5-sonnet-20241022"  # pinned
    openai_model: str = "gpt-4o-2024-08-06"  # pinned
    preferred_provider: str = "anthropic"
    log_level: str = "INFO"
    sentry_dsn: str = ""  # non-secret DSN; empty disables Sentry
    auth_token_ttl_seconds: int = 28800  # access-token lifetime ~8h (spec 4b FR-019)
    # Browser origins allowed to call the API (the SPA, spec 10). The SPA and API are
    # separate origins, so CORS is required for any browser request to succeed. Override
    # per environment (JSON list in env CORS_ALLOW_ORIGINS) with the real SPA origin(s).
    cors_allow_origins: list[str] = ["http://localhost:5173"]

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

    # Bootstrap manager (spec 4b FR-024): OPTIONAL, NOT in _REQUIRED_SECRETS (no ci.yml change).
    bootstrap_manager_email: str = ""
    bootstrap_manager_password: str = ""

    # --- Ingestion: optional source credentials (NOT in _REQUIRED_SECRETS — D7) ---
    pubmed_api_key: str = ""  # NCBI E-utilities API key; empty ⇒ keyless (10 req/s limit)
    openfda_api_key: str = ""  # openFDA API key; empty ⇒ keyless (240 req/min limit)

    # --- Ingestion: non-secret configuration ---
    ncbi_tool_email: str = "pantera@example.com"  # sent to NCBI as courtesy identification
    ingestion_initial_lookback_days: int = 365  # first-run lookback window (D9)
    ingestion_per_source_cap: int = 200  # max records fetched per source per run (D9)

    # --- Embedding: RAG index configuration (spec 6) ---
    embedder_tokenizer_path: str = "modelserver/models/tokenizer.json"  # tokenizer.json path
    embedder_model_version: str = ""  # pinned embedder SHA-256; from Vault (M3: fail-fast)
    chunk_target_tokens: int = 256  # target chunk size in tokens (approximate)
    chunk_overlap_ratio: float = 0.15  # overlap as fraction of target (15%)
    chunk_max_tokens: int = 512  # hard cap; chunks never exceed this

    # --- RAG retrieval: query cache configuration (spec 7) ---
    query_embedding_cache_ttl: int = 3600  # Redis TTL for query embedding cache entries (seconds)

    # --- Security hardening (spec 12) ---
    guardrails_url: str = "http://guardrails:8002"  # sidecar base URL (non-secret config)
    app_database_url: str = ""  # least-priv pantera_app DSN; from Vault (_REQUIRED_SECRETS)
    # Kill-switches are NON-PRODUCTION / TEST-ONLY: they let the test suite isolate
    # non-guarded / non-redacted behaviour. They MUST NEVER bypass the mandatory boundary in
    # production — startup (T002a) refuses to boot if either is False when environment==production
    # (FR-003 / FR-014a; Principle V). Default True so the boundary is always on by default.
    guardrails_enabled: bool = True
    redaction_enabled: bool = True

    # --- Triage (spec 8) ---
    modelserver_url: str = "http://modelserver:8001"
    triage_confidence_threshold: float = 0.70
    triage_staleness_max_age_minutes: int = 30
    triage_llm_max_tokens: int = 256

    # --- Report drafting agent (spec 9) ---
    agent_max_iterations: int = 8
    agent_max_tokens: int = 8000
    agent_llm_max_tokens: int = 2048
    report_redraft_cap: int = 3
    expedited_sla_hours: int = 24

    # --- LangSmith tracing (spec 10 FR-032/035) — optional; empty disables tracing ---
    # NOT in _REQUIRED_SECRETS: app boots normally when empty.
    langsmith_api_key: str = ""
    langsmith_project: str = "pantera"
    # Master switch: tracing requires BOTH this True AND a key. Default False. Traces carry
    # unredacted clinical text on the agent path — keep OFF in production until Presidio (spec 12).
    tracing_enabled: bool = False

    # --- ARQ worker / scheduler / dead-letter (spec 11) ---
    jobs_inline: bool = False  # dev/test only; startup forbids True unless dev_inline_ack (SC-008)
    # Explicit acknowledgement that jobs_inline=True is intentional (dev/test). Startup refuses
    # to boot with jobs_inline=True unless this is also set, so inline mode can never be enabled
    # by accident in production (SC-008). Read from env DEV_INLINE_ACK; replaces the prior
    # os.environ lookup in lifespan (config.py is the only place env is read).
    dev_inline_ack: bool = False
    worker_max_jobs: int = 10  # bounds expedited fan-out (FR-015c)
    worker_job_timeout: int = 600  # per-job seconds (index/draft can be slow)
    worker_shutdown_grace_seconds: int = 600  # default = job timeout (FR-012)
    scheduler_tick_cron_minute: int = 0  # hourly tick
    dead_letter_retention_days: int = 90  # FR-009a

    # Per-1K-token prices in USD, keyed by pinned model id.
    # Units: USD per 1,000 tokens (input or output). Currency: USD.
    # anthropic claude-3-5-sonnet-20241022: $3/$15 per M tokens = $0.003/$0.015 per 1K
    # openai gpt-4o-2024-08-06: $2.50/$10 per M tokens = $0.0025/$0.010 per 1K
    llm_price_per_1k_input_usd: dict = {
        "claude-3-5-sonnet-20241022": 0.003,
        "gpt-4o-2024-08-06": 0.0025,
    }
    llm_price_per_1k_output_usd: dict = {
        "claude-3-5-sonnet-20241022": 0.015,
        "gpt-4o-2024-08-06": 0.010,
    }


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide Settings singleton.

    Cached so that `load_secrets_from_vault(get_settings())` at startup populates the
    SAME instance every caller sees. Returning a fresh `Settings()` each call (the prior
    behaviour) meant secret-needing code reached via `get_settings()` (e.g. triage's LLM
    fallback) never saw the Vault-loaded secrets.
    """
    return Settings()
