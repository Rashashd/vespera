"""One-time helper to write Pantera's secrets into the dev Vault (KV v2)."""

import os

import hvac


def main() -> None:
    """Write the pantera/secrets KV from environment values (dev convenience)."""
    addr = os.environ.get("VAULT_ADDR", "http://localhost:8200")
    token = os.environ.get("VAULT_TOKEN", "root")
    client = hvac.Client(url=addr, token=token)
    if not client.is_authenticated():
        raise SystemExit(f"Cannot authenticate with Vault at {addr}")

    # Sensible local defaults that match docker-compose service names; override via env.
    secrets = {
        "database_url": os.environ.get(
            "DATABASE_URL", "postgresql+asyncpg://pantera:pantera@postgres:5432/pantera"
        ),
        "redis_url": os.environ.get("REDIS_URL", "redis://redis:6379/0"),
        "anthropic_api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
        "openai_api_key": os.environ.get("OPENAI_API_KEY", ""),
        "modelserver_token": os.environ.get("MODELSERVER_TOKEN", ""),
        "guardrails_token": os.environ.get("GUARDRAILS_TOKEN", ""),
    }
    if not (secrets["anthropic_api_key"] or secrets["openai_api_key"]):
        raise SystemExit("Set ANTHROPIC_API_KEY or OPENAI_API_KEY before writing secrets")

    client.secrets.kv.v2.create_or_update_secret(path="pantera/secrets", secret=secrets)
    print("Wrote secrets to Vault path 'pantera/secrets'")


if __name__ == "__main__":
    main()
