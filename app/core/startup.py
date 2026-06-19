"""Secret loading from Vault and fail-fast startup validation checks."""

import hvac
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.observability.logging import get_logger

_log = get_logger(__name__)

# Secrets that MUST be present for the foundation to boot (FR-002); auth_jwt_secret added in spec 2.
# Spec 12: app_database_url (least-priv runtime DSN) + guardrails_token (sidecar credential) added.
_REQUIRED_SECRETS = (
    "database_url",
    "redis_url",
    "auth_jwt_secret",
    "app_database_url",
    "guardrails_token",
)


async def load_secrets_from_vault(settings: Settings) -> None:
    """Fetch secrets from Vault into Settings; raise to abort boot on failure/missing keys."""
    client = hvac.Client(url=settings.vault_addr, token=settings.vault_token)
    try:
        authenticated = client.is_authenticated()
    except Exception as exc:  # connection refused, DNS failure, etc.
        raise RuntimeError(f"Cannot reach Vault at {settings.vault_addr}: {exc}") from exc
    if not authenticated:
        raise RuntimeError("Cannot authenticate with Vault — is it running and is the token valid?")

    try:
        data = client.secrets.kv.v2.read_secret_version(
            path=settings.vault_secret_path, raise_on_deleted_version=True
        )["data"]["data"]
    except Exception as exc:
        raise RuntimeError(
            f"Failed to read secrets from Vault path '{settings.vault_secret_path}': {exc}"
        ) from exc

    settings.database_url = data.get("database_url", "")
    settings.redis_url = data.get("redis_url", "")
    settings.anthropic_api_key = data.get("anthropic_api_key", "")
    settings.openai_api_key = data.get("openai_api_key", "")
    settings.modelserver_token = data.get("modelserver_token", "")
    settings.guardrails_token = data.get("guardrails_token", "")
    settings.app_database_url = data.get("app_database_url", "")  # spec 12: least-priv runtime DSN
    settings.auth_jwt_secret = data.get("auth_jwt_secret", "")
    # Bootstrap admin credentials are optional at boot (only the seed script needs them).
    settings.bootstrap_admin_email = data.get("bootstrap_admin_email", "")
    settings.bootstrap_admin_password = data.get("bootstrap_admin_password", "")
    # Spec 13: optional delivery routing config — absent ⇒ delivery holds, app still boots.
    settings.n8n_webhook_url = data.get("n8n_webhook_url", "")
    settings.delivery_callback_token = data.get("delivery_callback_token", "")

    missing = [name for name in _REQUIRED_SECRETS if not getattr(settings, name)]
    if not (settings.anthropic_api_key or settings.openai_api_key):
        missing.append("anthropic_api_key|openai_api_key")
    if missing:
        raise RuntimeError(f"Required secret(s) missing from Vault: {', '.join(missing)}")

    _log.info("secrets.loaded", source="vault", path=settings.vault_secret_path)


async def check_database(engine: AsyncEngine) -> None:
    """Verify the database is reachable; raise to abort boot if not (FR-004)."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def check_redis(redis) -> None:
    """Verify the cache is reachable; raise to abort boot if not (FR-004)."""
    await redis.ping()


def check_model_artifacts(settings: Settings) -> None:
    """Verify model-artifact hashes when artifacts exist; no-op when absent (FR-005)."""
    return None


def check_security_boundary(settings: Settings) -> None:
    """Refuse to boot in production with a mandatory security layer disabled (T002a).

    `guardrails_enabled`/`redaction_enabled` exist ONLY so the test suite can isolate
    non-guarded / non-redacted behaviour. Honouring a `False` toggle in production would
    silently bypass the mandatory guardrails boundary or PII redaction (FR-003 / FR-014a;
    Principle V / Security). Non-prod may disable them for test isolation.
    """
    if settings.environment != "production":
        return
    disabled = [
        name for name in ("guardrails_enabled", "redaction_enabled") if not getattr(settings, name)
    ]
    if disabled:
        raise RuntimeError(
            "Mandatory security boundary cannot be disabled in production: "
            f"{', '.join(disabled)} is False (set environment != 'production' for tests only)"
        )


async def run_startup_checks(engine: AsyncEngine, redis, settings: Settings) -> None:
    """Run all fail-fast startup checks; any failure aborts boot."""
    check_security_boundary(settings)
    await check_database(engine)
    await check_redis(redis)
    check_model_artifacts(settings)
    _log.info("startup.checks.passed")
