# Research & Design Decisions: Staff & Client Account Model

**Feature**: 004b-staff-and-clients · **Date**: 2026-06-09 · **Migration**: `0005_staff_and_clients.py`

Each decision records what was chosen, why, and the alternatives rejected. All resolve directly from
the spec's Clarifications; no open `NEEDS CLARIFICATION` remained at plan start.

## D1 — User typing: `user_type` column distinct from `role`

**Decision**: Add `users.user_type` (`StrEnum` `staff`|`client`, `String(8)` + CHECK) separate from
`role`. Staff: `user_type='staff'`, `client_id IS NULL`, `role ∈ {manager,admin,reviewer}`. Client:
`user_type='client'`, `client_id` set, `role='client_user'`. Enforced by a table CHECK:
`(user_type='staff' AND client_id IS NULL) OR (user_type='client' AND client_id IS NOT NULL)`.

**Rationale**: Keeps the staff role hierarchy and the client population orthogonal; client-user
sub-roles (a future improvement) can grow without touching staff roles (spec clarification).

**Alternatives**: One flat role enum (`manager/staff_admin/staff_reviewer/client_user`) — rejected:
overloads role with population; distinguishing by `client_id` NULL alone — rejected: one column, two
meanings, easy to get wrong (the user's own concern).

## D2 — Role enum expansion + CHECK migration

**Decision**: `Role` gains `MANAGER="manager"` and `CLIENT_USER="client_user"` (keeps `admin`,
`reviewer`). Migration `0005` drops `ck_users_role` (`role IN ('admin','reviewer')`) and recreates it
as `role IN ('manager','admin','reviewer','client_user')`.

**Rationale**: Mirrors the spec-2/3 `String`+CHECK+`StrEnum` pattern; total CHECK keeps invalid roles
out at the DB layer.

**Alternatives**: Postgres native ENUM type — rejected: project convention is String+CHECK for cheap,
reversible enum changes.

## D3 — Email uniqueness already satisfied

**Decision**: Global email uniqueness (FR-025) needs **no new constraint** — fastapi-users'
`SQLAlchemyBaseUserTable` already defines a unique, indexed `email`. Keep it; document it as the
enforcement point.

**Rationale**: Reuse the existing unique index; one email = one account spanning staff and client-users.

**Alternatives**: Per-client email uniqueness — rejected at clarify (login ambiguity, departs from
email-as-login).

## D4 — Client-user scope representation

**Decision**: Model the scope as: `users.client_scope` (`StrEnum` `full`|`scoped`, nullable — set only
for client-users) + `users.min_severity` (severity `StrEnum`, nullable, used when `scoped`) + a junction
table **`user_watchlist_scope`** (`user_id`, `watchlist_id`, `client_id`; FK `ON DELETE CASCADE`;
UNIQUE `(user_id, watchlist_id)`; indexed). Semantics: `full` ⇒ all of the client's reports;
`scoped` ⇒ narrowed by `min_severity` and/or the linked watchlists; **absent/empty ⇒ no visibility**
(default-deny). Creation MUST set `client_scope` explicitly and, when `scoped`, supply at least one of
`min_severity` or ≥1 watchlist (FR-014).

**Rationale**: A single column captures the full-vs-scoped intent; severity is one value (column);
watchlist set is many-to-many (junction). Default-deny is the fail-safe the spec mandates.

**Alternatives**: A JSON scope blob — rejected: not queryable/constrained; a separate `client_user_scope`
table with one row — rejected: extra join for two scalar fields that belong on the user.

## D5 — Client lifecycle reuses `clients.status`, not a new flag

**Decision**: Soft-delete = `clients.status='suspended'` (the column + `ck_clients_status` already
exist, and a `ClientSuspended` event exists); reactivate = `status='active'`. No `is_active` column is
added to `clients` (that flag is on `watchlists`). New work (ingestion triggers, client-user logins) is
refused when `status='suspended'`; all data is preserved; hard delete is never offered.

**Rationale**: The spec's "flip the existing active flag" intent maps to the **existing** `status`
column; reuse beats adding a parallel flag. Corrects the spec's `is_active` wording for clients.

**Alternatives**: Add `clients.is_active` — rejected: duplicates `status`, two sources of truth.

## D6 — Where the scope junction model lives

**Decision**: Put `UserWatchlistScope` in `app/clients/models.py` (it references `watchlists` and
`clients`), and the scope **columns** (`client_scope`, `min_severity`) on `User` in `app/auth/models.py`.

**Rationale**: Keeps watchlist-referencing schema with the clients package; avoids a circular import
(auth → clients) by keeping only scalar columns on `User`.

**Alternatives**: Everything in `auth/models.py` — rejected: pulls watchlist FKs into the auth package.

## D7 — Bootstrap manager credential: OPTIONAL Vault secrets (no CI change)

**Decision**: Add `bootstrap_manager_email` and `bootstrap_manager_password` to `Settings` as
**optional** (default empty), loaded from Vault when present — **not** added to `_REQUIRED_SECRETS`
(mirrors the optional ingestion keys, D7 of spec 4). The seed reads them into memory only. When unset
(dev/CI), fall back to a documented non-secret default email + a generated password that the
force-change-on-first-login flow rotates. This honors "credential from Vault" **and** the spec's "no new
**required** secret / no `ci.yml` change."

**Rationale**: A required bootstrap secret would force the spec-2 CI-secret-writer change the spec
explicitly avoided; optional+fallback keeps boot/migration green everywhere while real deployments set
the Vault values.

**Alternatives**: Required secret — rejected (forces CI change, contradicts spec). Random password
surfaced once — viable but less reproducible for tests; kept as the production behavior via Vault.

## D8 — Idempotent bootstrap seed (no duplicate managers)

**Decision**: Create the bootstrap manager in **two guarded places**: (a) the migration `0005` data
step inserts it after the reset (runs once via Alembic), and (b) `app/auth/bootstrap.ensure_manager()`
called from `lifespan` startup creates it **only if no active manager exists** (safety net for fresh
DBs / re-seeds). Email uniqueness (D3) makes a double-insert a no-op/skip. Password is changeable after
first login (reuses the fastapi-users password update path; force-change is the intended hardening).

**Rationale**: Answers the user's concern directly — re-running migrations, re-seeding Vault, or
restarting never creates a second manager.

**Alternatives**: Seed only in migration — rejected: a fresh dev DB created outside Alembic data steps
could have no manager; the startup safety net covers it idempotently.

## D9 — Session freshness: re-read DB each request + ~8h TTL

**Decision**: Keep the fastapi-users `current_user(active=True)` dependency (it already loads the user
row from the DB each request, so `is_active`, `role`, `user_type` are always fresh). Add a thin
`current_active_principal` wrapper that, for `user_type='client'`, also rejects the request if the
user's client `status != 'active'`. Set `auth_token_ttl_seconds` 1800 → **28800 (~8h)**; expiry ends
the session (no refresh token). Token claims are never trusted for authorization — only identity.

**Rationale**: Immediate revocation (demotion/deactivation/suspend) on the next request without new
infra; the long TTL is acceptable defense-in-depth because revocation is DB-driven (clarification).

**Alternatives**: Short TTL + refresh token — deferred to future improvement; Redis denylist —
rejected: extra stateful infra for marginal gain over the DB re-check.

## D10 — Acting-client context = validated path parameter

**Decision**: Express the target client as a **path parameter** on staff client-scoped routes
(`/clients/{client_id}/...`), resolved by a reusable `acting_client` dependency that loads the client,
404s if missing, and (for new work) 400s if `suspended`. Staff may target any client; a client-user may
target only their own `client_id` (else 404, no existence leak). The client **roster list**
(`GET /clients`) is readable by all staff; mutation is manager-only.

**Rationale**: Path params are explicit, audit-friendly (the target client is in the route), and avoid
an implicit "all clients" default. Matches REST conventions already used (`/watchlists/{id}/...`).

**Alternatives**: `X-Client-Id` header — rejected: less discoverable, easy to omit; a per-session
"current client" — rejected: hidden state, harder to audit.

## D11 — Audit attribution carries `target_client_id`

**Decision**: New/extended domain events carry `target_client_id`; the audit handler
(`app/audit/handler.py`) persists it as the acted-upon client (a staff actor's own `client_id` is
NULL). Events: reuse `UserCreated`/`UserRoleChanged`/`UserDeactivated` for staff (client_id NULL), add
`ClientReactivated`, `ClientReportEmailChanged`, `ClientUserCreated`, `ClientUserScopeChanged` (all with
`target_client_id`). Reuse `ClientCreated`/`ClientSuspended`. Audit rows remain append-only (no
update/delete path) — already the case; assert it in tests.

**Rationale**: Reuses the spec-2 dispatcher + passive audit listener; the `target_client_id` field
already exists on several events, so this is mostly enforcement + a couple of new event classes.

**Alternatives**: A separate access-log table — deferred (read-auditing is a later spec).

## D12 — Migration `0005` data reset scope

**Decision**: `0005` (down_revision `0004`) order: (1) additive schema — `users` columns + CHECK
changes (drop/recreate `ck_users_role`, add integrity CHECK, `client_id` → nullable), `clients` report
columns + threshold CHECK, create `user_watchlist_scope`; (2) **data reset** — DELETE
`ingestion_run_sources`, `ingestion_runs`, and audit rows whose actor is a user, then DELETE `users`
(FK-safe order); (3) seed one bootstrap manager. Preserve `documents`, `document_*`, `watchlists`,
`watchlist_items`, `source_watermarks` (no user FK). Down-migration drops the new columns/table and
restores the two-role CHECK (data reset is not reversible — documented; acceptable for a dev system).

**Rationale**: FK-safe deletion order prevents dangling references; preserving non-user-FK data keeps
the spec-4 corpus intact; the apparent FR-020-vs-wipe tension is resolved because immutability is a
runtime guarantee, not a one-time-migration constraint (clarification).

**Alternatives**: Make `client_id` nullable + backfill existing users → staff — rejected at clarify
(silent cross-client grant). Keep audit rows with nulled actors — rejected (nullable FK + orphans for
no pre-launch benefit).
