# Data Model: Staff & Client Account Model

**Feature**: 004b-staff-and-clients · **Date**: 2026-06-09 · **Migration**: `0005_staff_and_clients.py`
(down_revision `0004`)

Enums are `String` columns with CHECK constraints mirrored by `StrEnum`s. Timestamps are tz-aware.
Reuses spec-2 `users`, spec-3 `clients`/`watchlists`. Email uniqueness is the existing fastapi-users
unique `email` index (D3).

## Enums

| Enum | Values | Location | Notes |
|------|--------|----------|-------|
| `UserType` | `staff`, `client` | `app/auth/schemas.py` | new; separate from role (D1) |
| `Role` (expanded) | `manager`, `admin`, `reviewer`, `client_user` | `app/auth/schemas.py` | adds `manager`, `client_user` (D2) |
| `ClientScope` | `full`, `scoped` | `app/auth/schemas.py` | client-user visibility mode (D4); NULL for staff |
| `SeverityLevel` (reused) | `non-serious` < `serious` < `life-threatening` | `app/clients/enums.py` | reused for `min_severity` + `urgent_severity_threshold` |

## `users` — ADDITIVE columns + constraint changes (spec-2 table)

| Column | Type | Notes |
|--------|------|-------|
| `user_type` | String(8), not null, default `staff` | `UserType`; backfill irrelevant (rows wiped, D12) |
| `client_id` | BigInteger, FK `clients.id`, **now nullable** | NULL ⇔ staff; set ⇔ client-user (D1) |
| `client_scope` | String(8), nullable | `ClientScope`; set only for client-users (D4) |
| `min_severity` | String(20), nullable | `SeverityLevel`; used when `client_scope='scoped'` (D4) |

**Constraint changes**:
- DROP `ck_users_role` (`role IN ('admin','reviewer')`) → RECREATE
  `ck_users_role` = `role IN ('manager','admin','reviewer','client_user')`.
- ADD `ck_users_type_client` =
  `(user_type='staff' AND client_id IS NULL) OR (user_type='client' AND client_id IS NOT NULL)`.
- ADD `ck_users_client_scope` =
  `client_scope IS NULL OR client_scope IN ('full','scoped')`.
- ADD `ck_users_min_severity` =
  `min_severity IS NULL OR min_severity IN ('non-serious','serious','life-threatening')`.
- Keep existing unique `email` index (global uniqueness, D3) and `ix_users_client_id`.
- Make `client_id` nullable on the existing `fk_users_client_id_clients` FK.

**Application invariants (validated in service, not all expressible as CHECK)**:
- Staff ⇒ `role ∈ {manager,admin,reviewer}`, `client_scope`/`min_severity` NULL, no scope links.
- Client-user ⇒ `role='client_user'`, `client_scope` set; if `scoped`, at least one of `min_severity`
  or ≥1 `user_watchlist_scope` row; absent/empty ⇒ **no visibility** (default-deny, FR-014).

## `clients` — ADDITIVE columns (spec-3 table)

| Column | Type | Notes |
|--------|------|-------|
| `report_email_regular` | String(320), nullable | single regular recipient (FR-017) |
| `report_email_urgent` | String(320), nullable | single urgent recipient (FR-017) |
| `urgent_severity_threshold` | String(20), not null, default `life-threatening` | `SeverityLevel` (FR-017/FR-018) |

**Constraints**: ADD `ck_clients_urgent_threshold` =
`urgent_severity_threshold IN ('non-serious','serious','life-threatening')`. Email format validated at
the Pydantic boundary (`EmailStr`), not by CHECK. Lifecycle reuses existing `status`
(`active`/`suspended`, `ck_clients_status`) — soft-delete = `suspended`, reactivate = `active` (D5);
**no hard delete** (FR-012).

## `user_watchlist_scope` — NEW junction (which watchlists a client-user may see)

| Column | Type | Notes |
|--------|------|-------|
| `id` | BigInteger PK | |
| `user_id` | BigInteger, FK `users.id` ON DELETE CASCADE, not null | the client-user |
| `watchlist_id` | BigInteger, FK `watchlists.id` ON DELETE CASCADE, not null | must belong to the user's client |
| `client_id` | BigInteger, not null | tenant scope (denormalized; equals the user's & watchlist's client) |
| `created_at` | DateTime(tz), not null, default now | |

**Constraints/Indexes**: `ux_user_watchlist_scope` UNIQUE `(user_id, watchlist_id)` (idempotent);
`ix_user_watchlist_scope_user_id`; `ix_user_watchlist_scope_client_id`. Service enforces that
`watchlist.client_id == user.client_id` before insert (FR-014 cross-client refusal). Scope rows persist
through watchlist **soft-deactivation**; only a hard-delete cascades them away (spec Edge Cases).

## Relationships

```
clients (spec 3) ──1:N── users (client-users; client_id set)        (staff have client_id NULL)
clients ──1:N── user_watchlist_scope                                 (tenant scope)
users ──1:N── user_watchlist_scope ──N:1── watchlists (spec 3)       (client-user visibility set)
clients + report_email_regular/urgent + urgent_severity_threshold    (report delivery config)
users (acting staff) ──→ ingestion_runs.triggered_by_user_id         (now any client's run; target_client recorded)
```

## Domain events (audit) — `app/domain/events.py`

| Event | Carries | Reuse/New |
|-------|---------|-----------|
| `UserCreated` / `UserRoleChanged` / `UserDeactivated` | `target_user_id`, role fields; `client_id` NULL for staff | reuse (staff CRUD) |
| `ClientCreated` / `ClientSuspended` | `target_client_id` | reuse (lifecycle) |
| `ClientReactivated` | `target_client_id` | **new** |
| `ClientReportEmailChanged` | `target_client_id`, `changes` | **new** |
| `ClientUserCreated` | `target_client_id`, `target_user_id`, `client_scope` | **new** |
| `ClientUserScopeChanged` | `target_client_id`, `target_user_id`, `changes` | **new** |
| `WatchlistActivationChanged` | `target_client_id`, `watchlist_id`, `is_active` | **new** (FR-027: staff-admin watchlist (de)activation) |

The audit handler persists `target_client_id` as the acted-upon client (D11). Audit log is append-only
even for a manager (FR-020) — no update/delete path exists; asserted in tests.

## State & validation rules (from requirements)

- **Staff/client integrity (FR-001)**: `ck_users_type_client` + service guards on create/update.
- **Manager minting (FR-004)**: only a manager may create/promote to `manager` — service guard.
- **Last manager (FR-005)**: refuse demote/deactivate (incl. self) when no other active manager remains
  — `_active_manager_count()` guard (mirrors the spec-2 last-admin guard).
- **Immutable identity (FR-009)**: `user_type`/`client_id` not accepted from the body; changes
  manager-only and audited.
- **Acting-client (FR-008)**: `{client_id}` path param validated; staff any, client-user own only;
  new work refused on `suspended`.
- **Client-user scope (FR-014/015)**: explicit `client_scope` at creation; `scoped` requires ≥1 of
  severity/watchlist; absent/empty ⇒ no visibility; cross-client watchlist refused; self-widening
  refused.
- **Lifecycle (FR-011/012)**: `suspended` freezes new work + client-user login; data preserved;
  reactivate restores; no hard delete.
- **Report emails (FR-017)**: single regular + single urgent (EmailStr) + threshold (default
  life-threatening); malformed refused; admin/manager only.
- **Freshness (FR-019)**: authorize from current DB row each request; client-user also gated on client
  `status`; access token ~8h, no refresh.
- **Migration (FR-023/024, D12)**: additive schema → FK-safe dev reset → idempotent bootstrap manager;
  preserve non-user-FK data.
