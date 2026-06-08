# Quickstart & Validation: Platform Foundation

Runnable scenarios that prove the foundation works end-to-end. Implementation details live
in `tasks.md` (next phase) and the source tree; this is a run/validation guide.

## Prerequisites

- Docker + Docker Compose
- `uv` (for running tests locally outside containers)
- A fresh clone of the repo on branch `001-platform-foundation`

## Bootstrap (one-time secret write)

1. Copy `.env.example` to `.env` — it documents only `VAULT_ADDR` and `VAULT_TOKEN`
   (no real secrets).
2. `docker compose up -d vault postgres redis`
3. Write secrets into Vault once (KV v2 path `pantera/secrets`): `database_url`,
   `redis_url`, and at least one of `anthropic_api_key` / `openai_api_key`. (A helper
   script is provided by the implementation phase.)

## Scenario 1 — Stack boots healthy (SC-001, US1)

```bash
docker compose up -d
curl -fsS http://localhost:8000/health   # → {"status":"ok"}
```

**Expected**: all containers healthy; `/health` returns 200 `{"status":"ok"}` quickly.

## Scenario 2 — Fail-fast on missing dependency (SC-002, US1)

For each of Vault, Postgres, Redis: stop that service, restart the `api` container, and
confirm it **refuses to boot** with an error naming the missing dependency; `/health` is
not reachable.

```bash
docker compose stop vault && docker compose up -d --force-recreate api
docker compose logs api   # → clear error naming Vault; container not serving
```

## Scenario 3 — No secrets in repo or logs (SC-003, US2)

```bash
gitleaks detect --no-banner          # → 0 findings (working tree + history)
docker compose logs api | grep -i -E "api_key|password|secret"   # → no secret values
```

## Scenario 4 — Security headers present (SC-007, US5)

```bash
curl -sI http://localhost:8000/health   # → HSTS, X-Frame-Options: DENY, nosniff, CSP
```

## Scenario 5 — Audit atomicity (SC-006, US4)

Run the integration test that dispatches a domain event with a forced audit-write failure
and asserts the originating state change is rolled back (no orphaned state, no audit row):

```bash
uv run pytest tests/integration/test_audit_atomicity.py -q
```

Also assert the happy path: one dispatched event → exactly one `audit_log` row.

## Scenario 6 — Worker bootstrap parity (FR-020)

```bash
docker compose logs worker   # → worker loads secrets + engine + redis identically, idles (no jobs)
```

## Scenario 7 — Config fail-fast (SC-009)

Set an unknown config field in the `api` environment and restart; confirm the app refuses to
start (pydantic `extra="forbid"`) rather than booting with unvalidated config.

## Full test + coverage

```bash
uv run pytest --cov=app --cov-report=term-missing
```

**Expected**: ≥80% line coverage overall; ≥95% on the audit DB-write path.
