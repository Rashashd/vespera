# Data Model: Client & Watchlist Management

Four new tables plus one new foreign key on the existing `users` table. All tenant-scoped tables
carry an indexed `client_id` (Constitution V / `app/db/CONVENTIONS.md`). Small enums are `String`
+ `CHECK` constraints (research D3), mirrored by `StrEnum`s in `app/clients/enums.py`. PKs are
`BigInteger` autoincrement, matching `users`/`audit_log`.

## Enums (`app/clients/enums.py`)

| Enum | Values | Default |
|------|--------|---------|
| `ClientStatus` | `active`, `suspended` | `active` |
| `Cadence` | `daily`, `weekly`, `monthly` | `weekly` (FR-006) |
| `SeverityLevel` (ordered) | `non-serious` < `serious` < `life-threatening` | `serious` (FR-007) |
| `WatchlistItemType` | `drug`, `mesh`, `keyword` | — |

`SeverityLevel` exposes an explicit order (for "minimum level that escalates"); reused by spec 8.

## `clients`

The first-class tenant record (FR-001/FR-002). Backs the spec-1 `client_id` boundary.

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | BigInteger | PK, autoincrement |
| `name` | String(255) | NOT NULL; unique on `lower(name)` (research D6) |
| `status` | String(16) | NOT NULL, default `active`; `CHECK status IN ('active','suspended')` |
| `created_at` | DateTime(tz) | NOT NULL, server default `now()` |
| `updated_at` | DateTime(tz) | NOT NULL, server default `now()`, `onupdate now()` |

Indexes: `ux_clients_lower_name` (unique, functional on `lower(name)`).

Relationships: `users.client_id → clients.id` (FK added by this migration); `watchlists.client_id
→ clients.id`.

## `watchlists`

A named monitoring group owning its own cadence, severity threshold, and budget (FR-003/006/007/009).

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | BigInteger | PK, autoincrement |
| `client_id` | BigInteger | NOT NULL, FK → `clients.id`, indexed |
| `name` | String(255) | NOT NULL |
| `cadence` | String(16) | NOT NULL, default `weekly`; `CHECK IN ('daily','weekly','monthly')` |
| `severity_threshold` | String(20) | NOT NULL, default `serious`; `CHECK IN ('non-serious','serious','life-threatening')` |
| `budget_amount` | Numeric(12,4) | NULLABLE (null = no cap); `CHECK budget_amount >= 0` |
| `is_active` | Boolean | NOT NULL, default `true` (soft-delete; FR-017) |
| `created_at` | DateTime(tz) | NOT NULL, server default `now()` |
| `updated_at` | DateTime(tz) | NOT NULL, server default `now()`, `onupdate now()` |

Indexes / constraints:
- `ix_watchlists_client_id` on `client_id` (tenant filtering).
- `ux_watchlists_client_lower_name` UNIQUE on `(client_id, lower(name))` — name unique per client (FR-003).

State: `is_active=false` = soft-deleted (excluded from monitoring; data preserved). Empty-watchlist
invariant (≥1 item to be active) is enforced in the service layer (research D9), not the DB.

## `watchlist_items`

Members of a watchlist: drugs, MeSH terms, keywords in one table (research D2).

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | BigInteger | PK, autoincrement |
| `watchlist_id` | BigInteger | NOT NULL, FK → `watchlists.id` (ON DELETE CASCADE), indexed |
| `client_id` | BigInteger | NOT NULL, indexed (denormalized for tenant scoping per CONVENTIONS) |
| `item_type` | String(16) | NOT NULL; `CHECK IN ('drug','mesh','keyword')` |
| `value` | String(512) | NOT NULL (raw text; MeSH stored free-form — spec §Clarifications) |
| `normalized_value` | String(512) | NOT NULL (trimmed/lowercased; idempotency key) |
| `created_at` | DateTime(tz) | NOT NULL, server default `now()` |

Indexes / constraints:
- `ix_watchlist_items_watchlist_id`, `ix_watchlist_items_client_id`.
- `ux_watchlist_items_unique` UNIQUE on `(watchlist_id, item_type, normalized_value)` —
  idempotent membership (FR-005); a duplicate add is a no-op, not a new row.

## `watchlist_budget_usage`

Per-UTC-calendar-month accumulated spend for a watchlist (research D4). Schema owned here;
populated by later specs. Budget **state is derived from this**, never stored.

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | BigInteger | PK, autoincrement |
| `watchlist_id` | BigInteger | NOT NULL, FK → `watchlists.id` (ON DELETE CASCADE), indexed |
| `client_id` | BigInteger | NOT NULL, indexed |
| `period_start` | Date | NOT NULL (first day of the UTC calendar month) |
| `amount` | Numeric(12,4) | NOT NULL, default `0`; `CHECK amount >= 0` |
| `updated_at` | DateTime(tz) | NOT NULL, server default `now()`, `onupdate now()` |

Indexes / constraints:
- `ux_watchlist_budget_usage_period` UNIQUE on `(watchlist_id, period_start)`.

**Derived budget state** (computed in `service.py`, exposed in watchlist reads):

```
current = usage.amount for the current UTC month (0 if no row)
budget  = watchlist.budget_amount
state = "ok"          if budget is NULL or current < 0.80 * budget
      = "warning"     if 0.80 * budget <= current < budget
      = "soft_capped" if current >= budget
```

Auto-resume (FR-012) is implicit: a new month → no usage row → `current = 0` → `ok`; raising
`budget_amount` re-evaluates the same comparison → cap clears with no extra write.

> **Note on `ON DELETE CASCADE`**: watchlists and their children are **soft-deleted** in this
> spec (no hard delete), so the cascade never fires in normal operation — it is defensive,
> guarding only a future hard-delete or test teardown.

## Modified: `users`

- **Add** `FK users.client_id → clients.id` after reconciliation (research D5). Column type
  unchanged (BigInteger, NOT NULL). Existing `ix_users_client_id` index retained.

## `audit_log` (unchanged)

No schema change. New client/watchlist domain events (research D10) flow through the existing
dispatcher → one append-only row each, attributed to the acting admin (`actor_type='human'`,
`actor_user_id` set) in the same transaction as the change.

## Entity relationships

```text
clients (1) ─────< (N) users          [users.client_id → clients.id]   (FK added here)
clients (1) ─────< (N) watchlists      [watchlists.client_id → clients.id]
watchlists (1) ──< (N) watchlist_items [cascade delete]
watchlists (1) ──< (N) watchlist_budget_usage (one row per UTC month) [cascade delete]
```

## Validation rules (enforced at the Pydantic boundary + service layer)

| Rule | Source | Enforced where |
|------|--------|----------------|
| Client name non-empty, unique (case-insensitive) | FR-001 | schema + DB unique index → 409 |
| Watchlist name non-empty, unique per client (case-insensitive) | FR-003 | schema + DB unique index → 409 |
| Cadence ∈ {daily,weekly,monthly} | FR-006 | enum schema → 422; CHECK |
| Severity ∈ {non-serious,serious,life-threatening} | FR-007 | enum schema → 422; CHECK |
| Budget ≥ 0, numeric | FR-009 | schema → 422; CHECK |
| Watchlist must have ≥1 item to be active | FR-016 | service → 400 `WATCHLIST_EMPTY` |
| Duplicate item add is idempotent | FR-005 | service + DB unique → no-op |
| Removing absent item fails gracefully | FR-005 | service → 404 (or 204 no-op) |
| All ops scoped to caller's `client_id` | FR-004 | service queries; cross-tenant → 404 |
| Only admin writes; reviewer reads own client | FR-013 | `require_admin` / `current_active_user` |
