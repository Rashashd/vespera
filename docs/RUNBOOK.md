# RUNBOOK

Operational guide for running Pantera locally and in production.

## Local (Docker Compose)

1. `cp .env.example .env` (only `VAULT_ADDR` / `VAULT_TOKEN`; no real secrets).
2. `docker compose up -d vault postgres redis`
3. Write secrets into Vault once. `scripts/write_secrets.py` is a **local-only helper**
   (gitignored — not in a fresh clone). If present:
   `ANTHROPIC_API_KEY=... uv run python scripts/write_secrets.py`
   Otherwise write them with the Vault CLI:
   `docker compose exec -e VAULT_TOKEN=root vault vault kv put secret/pantera/secrets \
     database_url='postgresql+asyncpg://pantera:pantera@postgres:5432/pantera' \
     redis_url='redis://redis:6379/0' anthropic_api_key='<key>'`
4. Apply the baseline schema (in-container so hostnames resolve):
   `docker compose run --rm api alembic upgrade head`
5. `docker compose up -d` — then `curl http://localhost:8000/health` → `{"status":"ok"}`.
6. **Bootstrap the first admin** (spec 2; idempotent — a no-op if any user exists):
   `docker compose run --rm api python scripts/seed_admin.py`
   It reads `bootstrap_admin_email` / `bootstrap_admin_password` from Vault (defaults
   `admin@pantera.io` / `ChangeMe1!`; override via env before `write_secrets.py`, and change
   the password after first login). Use a deliverable email domain — `.local` is rejected.

## Authentication (spec 2)

- Log in: `POST /auth/jwt/login` (form `username`=email, `password`) → `{access_token,
  token_type:"bearer"}`. Send the token as `Authorization: Bearer <token>` on protected routes.
- Tokens are stateless JWTs (~30 min, no refresh); deactivating a user takes effect within one
  token lifetime. The signing key is the Vault secret `auth_jwt_secret` (required at boot).
- Login is rate-limited to **5/min per source IP** (429 when exceeded); there is no per-account
  lockout by design.
- Admin-only user management: `POST /users`, `GET /users`, `PATCH /users/{id}` — all scoped to
  the admin's `client_id`.

## Clients & watchlists (spec 3)

Tenant onboarding is an **operator script** (not an API), mirroring `seed_admin.py` — this avoids
an admin suspending their own client and locking themselves out. Migration `0003` also reconciles
every pre-existing `users.client_id` into a real `clients` row (named `Client <id>`) and adds the
`users.client_id → clients.id` foreign key.

- Create a client: `docker compose run --rm api python scripts/seed_client.py --name "Acme Pharma"`
  → prints the new client id. Duplicate names (case-insensitive) are rejected.
- Suspend / reactivate: `... scripts/seed_client.py --suspend <id>` / `--activate <id>`. No
  destructive delete — suspension only. Each action writes one audit row (system actor).

Client API (the caller only ever sees its **own** client; `client_id` comes from the token):

- `GET /clients/me` — read your client (any active user).
- `PATCH /clients/me {"name": "..."}` — rename your client (admin only; `status` is operator-only).

Watchlist API (base `/watchlists`; **writes require admin**, reads allow reviewer; everything is
client-scoped and a cross-tenant id returns 404):

- `POST /watchlists` — create a named watchlist with ≥1 item (`items: [{item_type, value}]`,
  `item_type ∈ drug|mesh|keyword`). Empty ⇒ 400 `WATCHLIST_EMPTY`; duplicate name ⇒ 409.
  Optional `cadence` (`daily|weekly|monthly`, default `weekly`), `severity_threshold`
  (`non-serious|serious|life-threatening`, default `serious`), `budget_amount` (≥0, null = no cap).
- `GET /watchlists` (`?include_inactive=true`), `GET /watchlists/{id}`.
- `PATCH /watchlists/{id}` — rename / set cadence,severity,budget / `is_active`. Deactivation is a
  **soft delete** (data preserved, excluded from monitoring).
- `POST /watchlists/{id}/items` (idempotent: 201 created, 200 duplicate no-op),
  `DELETE /watchlists/{id}/items/{item_id}` (graceful; refuses to empty an active watchlist).

Each watchlist read exposes a derived `budget_status` (`ok` < 80% → `warning` ≥ 80% →
`soft_capped` ≥ 100% of the current-UTC-month spend) and `current_period_spend`. Raising the
budget or a new month auto-clears the cap (spend metering itself arrives in a later spec).

## Literature ingestion (spec 4)

### Run model

An ingestion run is triggered via `POST /watchlists/{id}/ingest` (admin only). It fans out
concurrently across up to six source adapters (PubMed, Europe PMC, openFDA FAERS, openFDA Labels,
FDA MedWatch, EMA, MHRA). Each adapter is isolated: one failure → `partial_success`; all fail →
`failed`. Records are deduplicated per client by normalized external ID (DOI > PMID > source:id).

Run status is readable immediately via `GET /ingestion-runs/{id}`. The background task
updates it to `success`, `partial_success`, or `failed` when complete.

### Optional API keys

Two Vault secrets are **optional** (not required for boot): `pubmed_api_key` and
`openfda_api_key`. Without them the adapters use the unauthenticated rate-limited tier.
Add them to Vault if you hit 429 errors on those endpoints:
```
vault kv patch secret/pantera/secrets pubmed_api_key='<key>' openfda_api_key='<key>'
```

### MeSH validation

MeSH terms are validated at watchlist write time against the bundled slim heading list at
`app/ingestion/data/mesh_terms.txt`. Validity is stored per item (`mesh_validity`: `valid` |
`invalid` | `unvalidated`). Invalid terms are flagged but never rejected. The runner excludes
confirmed-invalid terms from PubMed MeSH targeting.

To regenerate the list from the full NLM distribution: `scripts/generate_mesh_list.py` (not
committed; see that file for operator instructions).

### Source watermarks

Each `(watchlist_id, source)` pair has a watermark (`source_watermarks` table). The first run
uses a lookback of `ingestion_initial_lookback_days` (default 365). Subsequent runs use the
watermark from the previous successful run. Watermarks are only advanced on source success.

### Startup reconciliation

At startup the app sweeps any runs stuck in `running` (from a crash) and marks them `failed`.
This is idempotent and safe for re-runs.

## Startup behavior

- The app loads secrets from Vault first and **refuses to boot** if Vault, Postgres, or
  Redis is unavailable, or if a required secret is missing.
- At startup: MeSH artifact check (non-fatal warning if missing) and stale-run reconciliation.
- The worker uses the same bootstrap; jobs/cron arrive in the scheduling feature.

## Tests

- `uv run pytest` — runs unit + stack-free tests.
- `PANTERA_INTEGRATION=1 uv run pytest` — also runs tests that require the live stack.

## Troubleshooting

- "Cannot reach Vault" → ensure the `vault` container is healthy and secrets were written.
- "Required secret(s) missing" → re-run `scripts/write_secrets.py` with the needed env vars.
- 429 on PubMed/openFDA → add the optional API keys to Vault (see Ingestion section above).
