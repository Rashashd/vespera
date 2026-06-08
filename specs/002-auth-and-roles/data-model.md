# Phase 1 Data Model: Authentication & Roles

Derived from spec.md Key Entities + Functional Requirements and research.md decisions. New
schema ships in Alembic revision `0002_auth` (depends on `0001` baseline), per
`app/db/CONVENTIONS.md`.

## Entity: User (`users` table) — NEW

The authenticatable person. Tenant-scoped, globally-unique email, one of two roles.

| Column | Type | Constraints | Notes / Source |
|--------|------|-------------|----------------|
| `id` | BigInteger | PK, autoincrement | Integer PK (research D4); coexists with audit sentinel 0 |
| `email` | String(320) | NOT NULL, UNIQUE (global), indexed | Login identity; normalized lowercase (FR-007, D12) |
| `hashed_password` | String | NOT NULL | argon2id hash; never returned/logged (FR-009, D2) |
| `role` | String(16) | NOT NULL, CHECK in (`admin`,`reviewer`) | Authorization level (FR-004, D6) |
| `is_active` | Boolean | NOT NULL, default true | Deactivation gate; false ⇒ cannot authenticate (FR-008) |
| `client_id` | BigInteger | NOT NULL, indexed | Tenant scope (FR-007, Constitution V). No FK yet — `clients` table arrives in spec 3, which may add the FK |
| `is_superuser` | Boolean | NOT NULL, default false | fastapi-users base field; unused by our authz (kept false) |
| `is_verified` | Boolean | NOT NULL, default true | fastapi-users base field; admin-provisioned users are verified on create (no email-verification flow in scope) |
| `created_at` | DateTime(tz) | NOT NULL, server default now() | Audit/forensics |
| `updated_at` | DateTime(tz) | NOT NULL, server default now(), onupdate now() | Tracks role/status changes |

**Indexes**: `ix_users_email` (unique), `ix_users_client_id`.

**Validation rules**:
- `email`: valid email format (pydantic `EmailStr`), normalized lowercase before persist.
- `role`: must be `admin` or `reviewer` (`Role` StrEnum).
- password (plaintext, at create/change only): ≥8 chars incl. ≥1 upper, ≥1 lower, ≥1 digit,
  ≥1 symbol (FR-016, enforced in `UserManager.validate_password`, D13).
- `client_id`: required; set by the acting admin's own client on create (never client-chosen).

**Relationships**:
- `User.client_id` → logical tenant (no FK constraint this spec; see note above).
- `AuditLog.actor_user_id` → `User.id` (nullable FK; D5).

## Entity change: AuditLog (`audit_log` table) — MODIFY

Add one nullable column; everything else from spec-1 is unchanged (append-only, sentinel rules
in `CONVENTIONS.md` preserved).

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `actor_user_id` | BigInteger | NULL, FK → `users.id` | Human-actor referential link; NULL for system events (sentinel 0 stays unlinked). Set by audit handler when `actor_type == "human"` (D5) |

**Index**: `ix_audit_log_actor_user_id` (partial/plain) for human-actor lookups.

**Invariant preserved**: `actor_id` remains `NOT NULL`; system events keep `actor_id = 0`,
`actor_type = "system"`, `actor_user_id = NULL`. Human events: `actor_id = user.id`,
`actor_type = "human"`, `actor_user_id = user.id`.

## Value object: Role (enum) — NEW

`Role(StrEnum)`: `ADMIN = "admin"`, `REVIEWER = "reviewer"`. Used in schemas, guards, and the
`role` column constraint. Exactly two values (FR-004); adding a value is a deliberate future
change.

## Domain events (audit producers) — NEW (in `app/domain/events.py`)

All subclass `DomainEvent(actor_id, actor_type, client_id)`; auto-registered with the audit
dispatcher. One `audit_log` row per event (SC-006).

| Event | Emitted when | actor | Payload (no secrets) |
|-------|--------------|-------|----------------------|
| `UserLoggedIn` | Successful login | human = user | `{user_id, email}` |
| `LoginFailed` | Failed login | human if email known else system(0) | `{email, reason}` (no password) |
| `UserCreated` | Admin creates a user | human = admin | `{target_user_id, target_email, role, client_id}` |
| `UserRoleChanged` | Admin changes a role | human = admin | `{target_user_id, old_role, new_role}` |
| `UserDeactivated` | Admin deactivates a user | human = admin | `{target_user_id, target_email}` |

## State & lifecycle

**User account states**: `active` (default on create) ⇄ `inactive` (admin deactivates).
- `active → inactive`: admin PATCH `is_active=false`. Blocks new authentication immediately;
  already-issued tokens remain valid until expiry (≤ token TTL; FR-001 tradeoff). Historical
  data and audit rows preserved (FR-008).
- `inactive → active`: admin PATCH `is_active=true` (reactivation; same client only).
- No `deleted` state in this spec (hard delete / erasure is spec 13).

**Role transitions**: `reviewer ⇄ admin` via admin PATCH `role`. Guarded by the **last-admin
invariant** (FR-013) and **escalation rule** (FR-014).

## Invariants (enforced in repository/manager layer)

1. **Tenant isolation** (FR-007, Constitution V): every read/write of `users` filters by the
   acting admin's `client_id`. A user of client A is invisible and immutable to an admin of
   client B → 404/403 (never reveal existence).
2. **Global email uniqueness** (FR-007, D12): unique index on normalized `email`; duplicate
   create → 400/409 with a non-leaking message.
3. **Last-admin guard** (FR-013): a PATCH that would deactivate or demote the *last active
   admin* of a client is rejected → 409.
4. **No escalation** (FR-014): only `admin` may change any `role`; a non-admin request never
   reaches `routes_users` (blocked by `require_admin` → 403). An admin cannot grant a role the
   model does not define.
5. **Password secrecy** (FR-009, SC-005): `hashed_password` is excluded from every response
   schema (`UserRead` has no password field) and never logged.
