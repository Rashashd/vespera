# Phase 0 Research: Authentication & Roles

All Technical Context unknowns are resolved below. Each decision records what was chosen, why,
and the alternatives rejected. References: spec.md (FR/SC), constitution.md, spec-1 code
(`app/`), `app/db/CONVENTIONS.md`.

## D1 — Auth library: fastapi-users

- **Decision**: Use `fastapi-users[sqlalchemy]` for the authentication backend, user-database
  adapter, password hashing, and JWT strategy. Wrap it in thin custom routes (see D7/D9).
- **Rationale**: Named in the approved build plan; mature, async-native, pydantic-based.
  Delegating credential hashing and JWT signing to a vetted library is *more* defensible than
  hand-rolling crypto under Constitution VII ("own every line" means defensible, not
  reinvented). Integrates with our async SQLAlchemy session.
- **Alternatives rejected**: (a) Hand-rolled JWT + passlib — more code to own and audit, higher
  crypto-bug risk. (b) Authlib/OAuth server — overkill; no SSO/OAuth in scope (Assumptions).

## D2 — Password hashing: argon2id

- **Decision**: Use argon2id via fastapi-users' password helper (pwdlib/argon2 backend).
- **Rationale**: Current OWASP/industry recommendation; memory-hard. fastapi-users supports it
  out of the box. Cost parameters are an implementation detail tuned in code (kept defensible).
- **Alternatives rejected**: bcrypt (acceptable but weaker against GPU attacks; 72-byte input
  limit). Plain PBKDF2 (weaker). Hashes are never logged or returned (FR-009, SC-005).

## D3 — Token strategy: stateless JWT, 30 min, Bearer, no refresh

- **Decision**: fastapi-users `JWTStrategy` with `lifetime_seconds=1800`, `BearerTransport`
  (tokenUrl `/auth/jwt/login`), HS256 signed with a Vault-sourced secret. No refresh token.
- **Rationale**: Matches the spec clarification (FR-001). Stateless = no session store to build
  or revoke; deactivation takes effect within ≤1 token lifetime (documented tradeoff). Bearer
  header is the standard for B2B API access.
- **Alternatives rejected**: Refresh-token pair (extra store + rotation/revocation surface, out
  of scope); cookie transport (CSRF surface, no SPA yet); long-lived tokens (larger theft window).
- **Token TTL** is exposed as a non-secret `Settings` field (`auth_token_ttl_seconds: int = 1800`)
  so it is config, not a magic number, per Configuration Discipline.

## D4 — User identity type: BigInteger PK

- **Decision**: `users.id` is a `BigInteger` autoincrement primary key (override fastapi-users'
  default UUID by declaring an int-typed base).
- **Rationale**: Consistent with the spec-1 schema (`audit_log` uses BigInteger ids and the
  integer sentinel `SYSTEM_ACTOR_ID = 0`). Lets the new `audit_log.actor_user_id` FK be a plain
  BigInteger that coexists with the sentinel (no user ever has id 0; FK is nullable). Internal
  B2B system — enumeration risk is low and ids are not exposed to untrusted parties.
- **Alternatives rejected**: UUID PK (fastapi-users default) — would make `actor_user_id` a UUID
  divergent from the integer `actor_id`, complicating the audit model for no real benefit here.

## D5 — Audit human-actor linkage: new nullable `actor_user_id` FK

- **Decision**: Add a new nullable column `audit_log.actor_user_id` with a FK → `users.id`.
  The audit handler sets it to `event.actor_id` when `actor_type == "human"`, else leaves it
  `NULL`. The existing non-null `actor_id` column (sentinel 0 for system) is unchanged.
- **Rationale**: The clarification requires "a nullable FK to `users.id` for human-originated
  events; the system sentinel (0) stays unlinked." The existing `actor_id` is `NOT NULL` and
  uses sentinel 0 — it cannot itself become a FK without a phantom user-0 row or breaking
  `CONVENTIONS.md`. A separate nullable FK column adds referential integrity for humans while
  keeping all spec-1 audit behavior and tests intact (non-breaking, per the carryover note).
- **Alternatives rejected**: (a) Convert `actor_id` to a nullable FK and use NULL for system —
  breaks the documented sentinel convention and existing tests. (b) Insert a synthetic user with
  id 0 — hacky, pollutes the users table, weakens "no active admin" logic.
- **Migration note**: `ON DELETE` is not a concern — users are deactivated, never deleted
  (FR-008); erasure is spec 13. FK is `ondelete=None` (restrict by default), which is fine since
  deletes don't occur.

## D6 — Role model & guards

- **Decision**: Store role as a `String(16)` column constrained to `{admin, reviewer}` via a
  Python `Role` `StrEnum` validated in pydantic schemas (DB-level CHECK optional). Provide
  FastAPI dependencies: `current_active_user` (from fastapi-users, → 401 if unauthenticated/
  inactive), and a `require_role(*roles)` factory returning `current_active_user` then raising
  `403` if `user.role` not in the allowed set. Expose `require_admin` and `require_reviewer`.
- **Rationale**: Cleanly separates 401 (unauthenticated) from 403 (forbidden) per FR-005/US2.
  The factory is the reusable guard every later spec imports. A small enum keeps the two-role
  constraint explicit (FR-004) and avoids an opaque permission system (Constitution simplicity).
- **Alternatives rejected**: fastapi-users `is_superuser` boolean — only models one privileged
  bit, can't express the admin/reviewer distinction. A full RBAC/permissions table — over-built
  for two fixed roles (YAGNI; Constitution VI).

## D7 — Login route: custom thin route (rate-limited + audited)

- **Decision**: Do **not** mount fastapi-users' stock `get_auth_router` login. Instead define a
  custom `POST /auth/jwt/login` that: (1) is decorated with `@limiter.limit("5/minute")`
  (slowapi, keyed on remote IP); (2) calls the fastapi-users `UserManager.authenticate`; (3) on
  success issues the JWT via the strategy and dispatches a `UserLoggedIn` event; (4) on failure
  dispatches `LoginFailed` and returns a generic 400/401 that does not reveal whether the email
  exists (FR-002). Logout (`POST /auth/jwt/logout`) is a no-op for stateless JWT (client discards
  token) but is provided for symmetry/204.
- **Rationale**: slowapi's `@limiter.limit` must decorate a route function we own — wrapping the
  login is the documented way to rate-limit it (FR-010). The custom route is *also* required to
  emit audit domain events (FR-012), which the stock router does not. Two independent
  justifications.
- **Alternatives rejected**: Global default rate limit (would throttle all endpoints, not just
  login); middleware path-matching hack (brittle). Mounting the stock router (can't attach the
  limiter or emit events).

## D8 — Auth domain events (audit integration)

- **Decision**: Add five frozen dataclass events in `app/domain/events.py`, all subclassing the
  existing `DomainEvent` (`actor_id`, `actor_type`, `client_id`): `UserLoggedIn`,
  `LoginFailed`, `UserCreated`, `UserRoleChanged`, `UserDeactivated`. The existing
  `register_audit_handlers` auto-registers them (it walks `DomainEvent.__subclasses__()`), so the
  passive audit handler writes one `audit_log` row per event in the caller's transaction
  (atomic, per spec-1 pattern).
- **Attribution rules**:
  - `UserLoggedIn`: `actor_type="human"`, `actor_id`=the user's id, `client_id`=user's client.
  - `LoginFailed`: if the email maps to a known user → `actor_type="human"`, that user's id;
    if unknown → `actor_type="system"`, `actor_id=SYSTEM_ACTOR_ID (0)`. Payload stores the
    attempted email (account identifier, security-relevant; **not** patient PII) and never the
    password.
  - `UserCreated` / `UserRoleChanged` / `UserDeactivated`: `actor_type="human"`, `actor_id`=the
    acting admin; payload carries the target user id, target email, and (for role change) old→new
    role. The audit handler also fills `actor_user_id` for these human events (D5).
- **Rationale**: Reuses the spec-1 decoupling pattern exactly; auditing stays a passive listener
  (Constitution Engineering Standards). One row per event satisfies SC-006.
- **PII note**: Constitution V targets *patient* identifiers and pasted secrets. A user's login
  email is an account identifier essential to a security audit trail and is explicitly allowed in
  audit payloads; passwords/hashes are never included (FR-009).

## D9 — Admin user management: custom client-scoped router

- **Decision**: Custom `routes_users.py` guarded by `require_admin`, exposing client-scoped
  user management (create / list / update-role / deactivate). All queries filter by the acting
  admin's `client_id` (from the token). Not fastapi-users' stock users router.
- **Rationale**: The stock router is superuser-gated and **not** client-scoped; we need tenant
  isolation (FR-007, Constitution V), the last-admin guard (FR-013), escalation prevention
  (FR-014), and audit events (FR-012) — all custom logic. Repository-layer scoping is the
  enforcement point.
- **Endpoints** (see contracts/users.md): `POST /users`, `GET /users`, `PATCH /users/{id}`
  (role and/or is_active). No hard delete (deactivate only; FR-008).

## D10 — Bootstrap: operator-run idempotent seed script

- **Decision**: `scripts/seed_admin.py` loads secrets from Vault (reusing
  `load_secrets_from_vault` + new keys `bootstrap_admin_email`, `bootstrap_admin_password`,
  `bootstrap_admin_client_id`), checks whether any user exists, and if none, creates the first
  admin via the same `UserManager` (so the password is hashed and policy-validated). Idempotent:
  if users already exist it logs and exits 0 without changes. No HTTP surface.
- **Rationale**: Matches the clarification (FR-011) and the existing `scripts/write_secrets.py`
  operator-script pattern. Keeps the admin-only constraint intact (no public endpoint). Reusing
  the UserManager ensures the seeded admin obeys FR-009/FR-016.
- **Alternatives rejected**: Auto-seed on startup (runs implicitly, easy to misconfigure);
  public setup endpoint (externally reachable privileged path).

## D11 — JWT signing secret in Vault

- **Decision**: Add `auth_jwt_secret` to the Vault secret map and to `Settings` (empty default,
  populated at startup like `database_url`). Add it to the fail-fast `_REQUIRED_SECRETS` in
  `app/core/startup.py` so the app refuses to boot without it. `scripts/write_secrets.py` writes
  a generated secret. The bootstrap-admin credentials are also Vault keys (D10).
- **Rationale**: Constitution Security & Secrets — all secrets in Vault, fail-fast on missing.
  The JWT secret is a signing key; leaking or defaulting it would forge tokens.
- **Alternatives rejected**: `.env` / settings default (forbidden); per-deploy random secret in
  memory (would invalidate all tokens on restart — acceptable for dev but Vault gives stable,
  rotatable control).

## D12 — Email uniqueness & normalization

- **Decision**: Store email lowercased/normalized; enforce a single global `UNIQUE` index on
  `email`. Login lookup is case-insensitive by normalizing input before lookup.
- **Rationale**: FR-007 mandates global uniqueness so email→user/client is deterministic.
  Normalization prevents `A@x.com` vs `a@x.com` duplicates. fastapi-users already normalizes
  email on create.
- **Alternatives rejected**: Per-client uniqueness (rejected in clarification); citext extension
  (unnecessary — normalize-on-write + lower index is simpler and portable).

## D13 — Password policy enforcement point (FR-016)

- **Decision**: Enforce "≥8 chars incl. upper, lower, digit, symbol" in the fastapi-users
  `UserManager.validate_password` hook (raises `InvalidPasswordException` → 400 with a clear
  message). Applied on both create and password change. A pure helper
  `validate_password_policy(pw) -> None` is unit-tested stack-free.
- **Rationale**: `validate_password` is fastapi-users' designated extension point; centralizes
  the policy so create and change share it. Stack-free helper keeps the rule in the 95% unit
  coverage band.
- **Alternatives rejected**: Pydantic schema regex only (bypassed by the seed script / manager
  paths); DB CHECK (can't see plaintext). The manager hook is the single correct chokepoint.

## Open items deferred to implementation (not blocking)

- argon2 cost parameters (memory/time) — tune in `backend.py`; defensible defaults from
  fastapi-users/pwdlib.
- Exact slowapi error body shape — reuse spec-1's `_rate_limit_exceeded_handler` (already wired
  in `main.py`).
