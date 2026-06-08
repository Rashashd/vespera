# Research: Client & Watchlist Management

All spec-level ambiguities were resolved in three `/speckit-clarify` sessions (see spec.md §
Clarifications). This file records the **implementation decisions** that turn the clarified spec
into a buildable design. Format per decision: Decision / Rationale / Alternatives considered.

## D1 — Client onboarding surface (who creates a tenant)

**Decision**: New-client onboarding (create + suspend/reactivate) is an **operator script**
`scripts/seed_client.py`. The admin API only exposes `GET /clients/me` and `PATCH /clients/me`
(rename own client). Suspension is operator-only.

**Rationale**: Matches the spec-2 precedent (`seed_admin.py` for the bootstrap tenant action)
and the spec's Assumption that tenant onboarding is a platform-operator path. Letting an admin
suspend their own client would be a self-lockout footgun. Keeps the public surface minimal.

**Alternatives considered**: A platform-superadmin REST surface for client CRUD (an authenticated
operator account, e.g. via the existing `is_superuser` flag, with a cross-tenant
`/platform/clients` API) — a real "operator console" experience. **Deferred to its own later
spec** by explicit decision (2026-06-06): it is a cross-tenant capability needing its own
security review and pairs naturally with the deferred React Admin Console. Spec 3 keeps the lean
CLI script.

## D2 — Watchlist item storage: one table vs three

**Decision**: A single `watchlist_items` table with an `item_type` discriminator
(`drug` | `mesh` | `keyword`) and a `value` string, rather than three parallel tables.

**Rationale**: Leaner (Constitution VI) — one model, one set of indexes, one idempotency rule
(`UNIQUE(watchlist_id, item_type, normalized_value)`). The three item types share identical
shape and lifecycle. Querying "all items of a watchlist" is one indexed scan.

**Alternatives considered**: Separate `watchlist_drugs` / `watchlist_mesh` / `watchlist_keywords`
tables — more tables/indexes for no behavioral gain; rejected.

## D3 — Small enums as CHECK constraints, not native PG enums

**Decision**: `cadence`, `severity_threshold`, `clients.status`, and `watchlist_items.item_type`
are stored as `String` columns with `CHECK (... IN (...))` constraints; mirrored by Python
`StrEnum`s in `app/clients/enums.py`.

**Rationale**: Exactly the spec-2 pattern (`ck_users_role`). CHECK constraints avoid the painful
`ALTER TYPE ... ADD VALUE` migration story of native PG enums and keep the migration reversible.
The `StrEnum`s are importable by spec 8 (severity) and spec 11 (cadence).

**Alternatives considered**: Native `CREATE TYPE` enums — rejected for migration friction.

## D4 — Budget period & spend tracking model

**Decision**: Store the budget cap on the watchlist (`budget_amount`, nullable = no cap). Track
accumulated spend in a per-period child table `watchlist_budget_usage`
(`watchlist_id`, `client_id`, `period_start` = first day of the UTC calendar month, `amount`),
unique on `(watchlist_id, period_start)`. **Budget state is derived, never stored**:
`soft_capped` if current-period `amount ≥ budget_amount`; `warning` if `amount ≥ 0.80 ×
budget_amount`; else `ok`; always `ok` if `budget_amount` is null.

**Rationale**: Deriving state means an admin raising the budget (FR-012) or a new month starting
(new period row, amount 0) **auto-clears** the cap with no extra write — exactly the spec's
reset/auto-resume semantics. A per-period row gives a clean reset boundary and a natural audit
trail. Spend *population* belongs to later specs (spec 11); this spec owns the schema, the 80%
threshold, the derivation, and exposing the state. Tests simulate spend by writing usage rows.

**Alternatives considered**: (a) A single `current_spend` + `period_start` column pair on the
watchlist — loses per-month history and complicates reset. (b) Storing the state string —
requires a writer to flip it on budget-raise and on reset; redundant with derivation. Both
rejected.

## D5 — Reconciling existing `users.client_id` and adding the FK

**Decision**: In migration `0003`, after creating `clients`: `INSERT INTO clients (id, name,
status, ...) SELECT DISTINCT client_id, 'Client ' || client_id, 'active', now(), now() FROM
users`, ensure the bootstrap client id (default `1`) exists, fix the identity sequence with
`setval`, then add `FK users.client_id → clients.id`.

**Rationale**: Guarantees zero orphaned `users.client_id` (SC-001) before the FK is enforced.
Synthetic names `Client <id>` are unique by construction and satisfy the platform-unique-name
rule; an operator renames them later via `PATCH /clients/me`. Sequence fixup prevents a future
auto-id colliding with a back-filled id.

**Alternatives considered**: Adding the FK without back-fill — fails immediately if any user row
exists. Dropping/recreating `users` — destructive; rejected.

## D6 — Client name uniqueness: case-insensitive

**Decision**: Unique index on `lower(name)` for `clients`; the service trims and the DB enforces
case-insensitive uniqueness. Watchlist name uniqueness is `UNIQUE(client_id, lower(name))`.

**Rationale**: Prevents "Acme Pharma" vs "acme pharma" duplicate tenants (the clarified intent).
Functional unique index avoids a `citext` extension dependency (Constitution VI leanness).

**Alternatives considered**: `citext` column type — adds an extension for marginal benefit;
plain exact-match unique — allows case-variant duplicates; both rejected.

## D7 — Authorization split: admin writes, reviewer/any active user reads

**Decision**: All configuration **writes** use `require_admin`. Configuration **reads**
(`GET /clients/me`, `GET /watchlists`, `GET /watchlists/{id}`) use `current_active_user` and are
client-scoped, so a `reviewer` can view but not modify (FR-013). Unauthenticated → 401 before any
tenant check.

**Rationale**: Directly encodes FR-013. Reuses the spec-2 guards unchanged; no new authz code.

**Alternatives considered**: `require_reviewer` for reads — wrong, would exclude admins from
reading; rejected.

## D8 — Cross-tenant refusal convention

**Decision**: Any read/write targeting a watchlist (or client) not belonging to the caller's
`client_id` returns **404 `*_NOT_FOUND`** (never reveal existence), matching the spec-2 user
router. `client_id` always comes from the token, never the request body.

**Rationale**: Consistency with spec 2 and the multi-tenant-isolation NON-NEGOTIABLE (SC-003).

## D9 — Empty-watchlist rejection point

**Decision**: A watchlist MUST have ≥1 item to exist as active. Enforce at the **service layer**
on create (`POST /watchlists` requires a non-empty items list) and on any operation that would
empty an active watchlist or activate an empty one → `400 WATCHLIST_EMPTY`. The DB does not try
to enforce "≥1 child" (no clean constraint); the service owns the invariant.

**Rationale**: FR-016 chose reject-on-create/activate. Service-layer enforcement is testable and
gives a clear message; a DB trigger would be heavier and less transparent.

**Alternatives considered**: Allow empty drafts, block only at schedule time — deferred behavior
the spec explicitly rejected.

## D10 — Domain events for audit

**Decision**: Add frozen `DomainEvent` subclasses in `app/domain/events.py`: `ClientCreated`,
`ClientUpdated`, `ClientSuspended`, `WatchlistCreated`, `WatchlistUpdated`,
`WatchlistDeactivated`, `WatchlistItemAdded`, `WatchlistItemRemoved`. No handler changes needed.

**Rationale**: The existing `register_audit_handlers` auto-discovers `DomainEvent.__subclasses__`,
so new events are audited automatically (one append-only row each, same transaction). `Updated`
events carry enough payload (changed fields) to satisfy FR-015 without one event per field.

**Alternatives considered**: One event per config field — noisy; rejected in favor of a single
`WatchlistUpdated` carrying the diff.

## D11 — Budget amount type & currency

**Decision**: `budget_amount` and usage `amount` are `Numeric(12, 4)`, nullable budget = no cap.
Treated as an abstract cost unit (the LLM/API "cost" metered later); no currency modeling.

**Rationale**: `Numeric` avoids float drift on money-like values. Currency/units are out of scope
(spend metering is spec 11); a unitless number is sufficient to define budget states now.

## D12 — No new secrets / config

**Decision**: Nothing in this spec touches Vault. The 80% warning threshold and default
cadence/severity are code-level constants/enum defaults, not secrets or `Settings` fields. (If a
later spec makes the threshold configurable, it becomes a `Settings` value then.)

**Rationale**: Avoids the CI "required secret" footgun entirely (no `_REQUIRED_SECRETS` change,
no `ci.yml` writer change). Keeps the change additive and reproducible.
