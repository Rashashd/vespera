# RUNBOOK

Operational guide for running Pantera locally and in production.

## Local (Docker Compose)

1. `cp .env.example .env` (only `VAULT_ADDR` / `VAULT_TOKEN`; no real secrets).
2. `docker compose up -d vault postgres redis`
3. Write secrets into Vault once:
   `ANTHROPIC_API_KEY=... uv run python scripts/write_secrets.py`
4. Apply the baseline schema: `uv run alembic upgrade head`
5. `docker compose up -d` — then `curl http://localhost:8000/health` → `{"status":"ok"}`.

## Startup behavior

- The app loads secrets from Vault first and **refuses to boot** if Vault, Postgres, or
  Redis is unavailable, or if a required secret is missing.
- The worker uses the same bootstrap; jobs/cron arrive in the scheduling feature.

## Tests

- `uv run pytest` — runs unit + stack-free tests.
- `PANTERA_INTEGRATION=1 uv run pytest` — also runs tests that require the live stack.

## Troubleshooting

- "Cannot reach Vault" → ensure the `vault` container is healthy and secrets were written.
- "Required secret(s) missing" → re-run `scripts/write_secrets.py` with the needed env vars.
