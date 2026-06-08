# Quickstart: Client & Watchlist Management

End-to-end validation that this feature works. Implementation lives in `app/clients/`; details
are in [data-model.md](./data-model.md) and [contracts/](./contracts/). This guide is a
run/validate script, not implementation code.

## Prerequisites

- The stack up: `docker compose up -d --wait vault postgres redis` (see
  [dev-environment](../../memory/dev-environment.md)). On this host integration tests also need
  the gitignored `docker-compose.override.yml` (ports 5433/6380) + localhost secrets.
- Secrets written once: `uv run python scripts/write_secrets.py`.
- Migrations applied: `docker compose run --rm api alembic upgrade head` (applies `0003`).
- A seeded admin (spec 2): `uv run python scripts/seed_admin.py`.

## 1. Migration reconciles existing tenants (US1, SC-001)

After `alembic upgrade head` reaches `0003`:
- A `clients` row exists for every distinct pre-existing `users.client_id` (named `Client <id>`).
- `users.client_id` now has a FK to `clients.id`; no orphaned users.
- `alembic downgrade -1` cleanly removes the FK and the four new tables.

Verify: `test_migration_0003.py` (upgrade reconciliation + FK integrity + downgrade).

## 2. Onboard and rename a client (US1)

```bash
uv run python scripts/seed_client.py --name "Acme Pharma"   # prints new client id
```
Then, as an admin of that client, `GET /clients/me` returns it; `PATCH /clients/me {"name": ...}`
renames it. A second `seed_client.py --name "acme pharma"` is rejected (case-insensitive unique).

Verify: `test_clients.py`.

## 3. Create watchlists with items (US2, SC-002)

As an admin (`Authorization: Bearer <token>`):
- `POST /watchlists` with `name`, and `items: [{drug}, {mesh}, {keyword}]` → 201.
- `POST /watchlists` with `items: []` → 400 `WATCHLIST_EMPTY`.
- Create a second watchlist with a different name → both listed by `GET /watchlists`.
- Re-using a name within the client → 409 `WATCHLIST_NAME_TAKEN`; same name under a *different*
  client is allowed.
- Adding a duplicate item (`POST /watchlists/{id}/items`) → 200 no-op, item count unchanged (FR-005).

Verify: `test_watchlists.py`.

## 4. Configure cadence & severity (US3, US4)

- `PATCH /watchlists/{id}` with `cadence: "daily"` and `severity_threshold: "life-threatening"`
  → stored; a sibling watchlist keeps its own values.
- Unset values read back as defaults `weekly` / `serious`.
- Invalid `cadence: "hourly"` or `severity_threshold: "fatal"` → 422.

Verify: `test_watchlist_config.py`.

## 5. Budget warn → soft-cap → reset (US5, SC-006)

With `budget_amount = 100`:
- Simulate spend `= 80` (write a `watchlist_budget_usage` row for the current UTC month) →
  `GET` shows `budget_status: "warning"`, monitoring not paused.
- Spend `= 100` → `budget_status: "soft_capped"`; a sibling watchlist under budget stays `ok`
  (FR-011).
- `PATCH budget_amount = 200` → status flips back to `ok` (FR-012).
- New UTC month (no usage row) → status `ok` automatically (auto-resume).

Verify: `test_watchlist_budget.py` + pure-logic `test_budget_state.py`.

## 6. Authorization & isolation (US2, SC-003, SC-007)

- A `reviewer` can `GET /clients/me` and `GET /watchlists` but every write → 403.
- Unauthenticated → 401 before any tenant check.
- An admin of client A requesting client B's watchlist id → 404 (no reveal).

Verify: `test_clients_authz.py`.

## 7. Audit trail (SC-008)

Each create/update/suspend/deactivate/item-change adds exactly one `audit_log` row with
`actor_type='human'`, `actor_user_id` = the acting admin, in the same transaction.

Verify: assertions within the integration tests above.

## Gate checks before merge

```bash
uv run ruff check app worker tests scripts
uv run black --check app worker tests scripts
PANTERA_INTEGRATION=1 uv run pytest          # full suite green
```
Config-write paths ≥ 95% coverage; overall suite ≥ 80% (CI gate). No new Vault secret was added,
so `ci.yml`'s inline secret writer needs no change (research D12).
