---
description: "Task list for Authentication & Roles (spec 002)"
---

# Tasks: Authentication & Roles

**Input**: Design documents from `specs/002-auth-and-roles/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: INCLUDED — the constitution mandates 95%+ coverage on the auth and DB-write paths
(SC-007) and the quickstart names specific test files. Test tasks are first-class here.

**Organization**: Tasks grouped by the four user stories (US1/US2 = P1, US3/US4 = P2). Each
story is an independently testable increment. Commits are staged to keep each PR under the
constitution's 400-line limit (plan Complexity Tracking).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no incomplete dependencies)
- **[Story]**: US1–US4 for story-phase tasks; Setup/Foundational/Polish carry no story label
- All paths are repository-relative.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Dependency, configuration, and secret plumbing for auth.

- [X] T001 Add `fastapi-users[sqlalchemy]` to `pyproject.toml` dependencies and run `uv sync` to update the lockfile
- [X] T002 [P] Add auth config fields to `app/core/config.py`: `auth_jwt_secret: str = ""` (secret, Vault-populated), `auth_token_ttl_seconds: int = 1800`, `bootstrap_admin_email: str = ""`, `bootstrap_admin_password: str = ""`, `bootstrap_admin_client_id: int = 1`
- [X] T003 [P] Extend `scripts/write_secrets.py` to write `auth_jwt_secret` (generated) plus `bootstrap_admin_email`/`bootstrap_admin_password`/`bootstrap_admin_client_id` into the Vault secret map
- [X] T004 Load `auth_jwt_secret` in `app/core/startup.py` `load_secrets_from_vault()` and add it to `_REQUIRED_SECRETS` so boot fails fast when it is missing (research D11)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Identity schema, password hashing, token issuance/validation, and audit wiring that
ALL user stories build on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T005 [P] Add `Role(StrEnum)` (`admin`/`reviewer`) and pydantic schemas `UserRead`, `UserCreate`, `UserUpdate` in `app/auth/schemas.py` — `UserRead` MUST omit any password field (FR-009); `UserCreate.password` is validated for policy at the manager layer (data-model.md)
- [X] T006 Create `User` ORM model in `app/auth/models.py` using the fastapi-users SQLAlchemy base with a **BigInteger** PK (research D4): `email` (unique, indexed), `hashed_password`, `role` (String(16), CHECK in admin/reviewer), `is_active`, `client_id` (BigInteger, indexed), `created_at`/`updated_at` (data-model.md)
- [X] T007 Add nullable `actor_user_id` (BigInteger, FK → `users.id`) column + `ix_audit_log_actor_user_id` to `AuditLog` in `app/db/models.py`, leaving `actor_id`/sentinel behavior unchanged (research D5)
- [X] T008 Create Alembic migration `app/db/migrations/versions/0002_auth.py` (down_revision `0001`): create `users` table with its indexes and the email unique index, and `op.add_column` + index for `audit_log.actor_user_id` with the FK; provide `downgrade()` (drop column then table) — follow `app/db/CONVENTIONS.md`
- [X] T009 [P] Add 5 frozen-dataclass domain events in `app/domain/events.py` subclassing `DomainEvent`: `UserLoggedIn`, `LoginFailed`, `UserCreated`, `UserRoleChanged`, `UserDeactivated` (data-model.md payloads; no password fields)
- [X] T010 Update `app/audit/handler.py` `audit_log_handler` to populate `actor_user_id = event.actor_id` when `event.actor_type == "human"` (else leave NULL); extend `_target_for` to handle the new `target_user_id`/`user_id` event fields (research D5/D8)
- [X] T011 [P] Add pure helper `validate_password_policy(password) -> None` (≥8 chars incl. upper/lower/digit/symbol; raises on violation) in `app/auth/manager.py` (FR-016, research D13)
- [X] T012 Implement `UserManager` in `app/auth/manager.py`: `validate_password` calls T011's helper; `on_after_*` hooks dispatch the lifecycle domain events; integer-id parsing (depends on T006, T011)
- [X] T013 Implement the auth backend in `app/auth/backend.py`: SQLAlchemy user-db adapter (session from `get_session`), `JWTStrategy` (secret from `settings.auth_jwt_secret`, `lifetime_seconds=settings.auth_token_ttl_seconds`), `BearerTransport(tokenUrl="/auth/jwt/login")`, `AuthenticationBackend`, and the `FastAPIUsers` instance exposing `current_active_user` (depends on T006, T012, research D3/D7)

**Checkpoint**: A user can exist, a token can be minted and validated, and a protected endpoint
can require an authenticated active user. Audit attribution is ready.

---

## Phase 3: User Story 1 — Authenticate and obtain a session (Priority: P1) 🎯 MVP

**Goal**: A registered active user logs in and receives a token; protected endpoints reject
absent/expired/tampered tokens and deactivated users.

**Independent Test**: Seed a user, log in for a token, call a protected endpoint with/without the
token, and confirm bad credentials return a generic failure (no email enumeration).

### Tests for User Story 1

- [X] T014 [P] [US1] Add shared integration fixtures in `tests/integration/conftest.py`: app/ASGI client, DB session, and helpers to create + activate/deactivate users and obtain tokens (self-skips unless `PANTERA_INTEGRATION=1`)
- [X] T015 [P] [US1] Integration test `tests/integration/test_auth_login.py`: 200 + token on valid login; 400 generic on wrong password (no enumeration, FR-002); 401 with no/expired/tampered token (FR-003); 400 for a deactivated user (FR-008)
- [X] T016 [P] [US1] Unit test `tests/unit/test_auth_schemas.py`: `UserRead` never serializes a password/hash field; `UserCreate`/`UserUpdate` validate role and email (SC-005)
- [X] T016b [P] [US1] Unit test `tests/unit/test_password_policy.py`: `validate_password_policy` accepts a conforming password and rejects each violation (too short, missing upper/lower/digit/symbol) with the documented error (FR-016, SC-007); stack-free, exercises the T011 helper directly

### Implementation for User Story 1

- [X] T017 [US1] Implement `app/auth/routes_auth.py`: custom `POST /auth/jwt/login` using `UserManager.authenticate` + JWT strategy, dispatching `UserLoggedIn` on success and `LoginFailed` on failure (generic 400, no enumeration), plus stateless `POST /auth/jwt/logout` (204) (contracts/auth.md, research D7/D8)
- [X] T018 [US1] Register the auth router in `app/main.py` `create_app()` (after limiter/middleware setup)

**Checkpoint**: Login + token validation work end-to-end; US1 is independently demoable (MVP).

---

## Phase 4: User Story 2 — Enforce role-based authorization (Priority: P1)

**Goal**: Reusable role guards that allow the correct role and return 403 for the wrong role,
401 for unauthenticated — the mechanism every later spec imports.

**Independent Test**: Protect a test endpoint with an admin-only guard and another with a
reviewer-only guard; confirm each role passes its own and is refused (403) by the other, and
unauthenticated callers get 401.

### Tests for User Story 2

- [X] T019 [P] [US2] Unit test `tests/unit/test_role_guards.py`: `require_role` returns the user when the role matches and raises HTTP 403 when it does not; the unauthenticated path surfaces 401 (FR-005, SC-002)
- [X] T020 [P] [US2] Integration test `tests/integration/test_authz.py`: mount temporary admin-only and reviewer-only endpoints and assert the full role matrix (admin↔reviewer allow/deny) plus 401 for no token (US2 acceptance scenarios)

### Implementation for User Story 2

- [X] T021 [US2] Implement `app/auth/dependencies.py`: re-export `current_active_user` from the backend, add a `require_role(*roles)` dependency factory (401 if unauthenticated/inactive via `current_active_user`, else 403 if `user.role` not allowed), and convenience `require_admin` / `require_reviewer` (research D6)

**Checkpoint**: Role guards are available and proven; US3 can rely on `require_admin`.

---

## Phase 5: User Story 3 — Administer users within a client (Priority: P2)

**Goal**: Admins create, list, and deactivate users scoped to their own client, with last-admin
protection and escalation prevention; the first admin is bootstrappable.

**Independent Test**: As an admin, create a reviewer in the admin's client, list (own client
only), deactivate it (login then refused), and confirm last-admin and cross-tenant actions are
blocked.

**Depends on**: US2 (`require_admin`) and the Foundational phase.

### Tests for User Story 3

- [X] T022 [P] [US3] Integration test `tests/integration/test_users_admin.py`: create (201, client_id from token), list (own client only, SC-003), deactivate (then login 400), duplicate email (409), last-admin deactivate/demote (409, FR-013), non-admin blocked (403, FR-014), cross-tenant PATCH (404)
- [X] T023 [P] [US3] Integration test `tests/integration/test_auth_audit.py`: one `audit_log` row per security event with correct attribution — human events set `actor_user_id` (FK), unknown-email `LoginFailed` is system/sentinel-0/NULL, no password in any payload (FR-012, SC-005, SC-006)

### Implementation for User Story 3

- [X] T024 [US3] Implement `app/auth/routes_users.py` guarded by `require_admin`: `POST /users` (client_id from token, emits `UserCreated`), `GET /users` (client-scoped list), `PATCH /users/{id}` (role and/or is_active; 404 if not in admin's client; last-admin guard → 409; emits `UserRoleChanged`/`UserDeactivated`) (contracts/users.md, data-model.md invariants)
- [X] T025 [US3] Register the users router in `app/main.py` `create_app()`
- [X] T026 [US3] Implement `scripts/seed_admin.py`: load Vault secrets, exit idempotently if any user exists, else create the first admin via `UserManager` using the `bootstrap_admin_*` values (no HTTP surface, FR-011, research D10)

**Checkpoint**: Full client-scoped admin management + bootstrap + audit trail verified.

---

## Phase 6: User Story 4 — Resist brute-force on login (Priority: P2)

**Goal**: Login is throttled to 5 attempts/minute/IP; the 6th is rejected; the window resets.

**Independent Test**: Fire 6 logins in a minute from one source — first 5 processed, 6th → 429;
after the window, attempts succeed again.

**Depends on**: US1 (the login route) and the Foundational phase.

### Tests for User Story 4

- [X] T027 [P] [US4] Integration test `tests/integration/test_login_rate_limit.py`: 6 rapid attempts from one source → 6th returns 429; a legitimate within-budget login still succeeds; window-reset allows retry (FR-010, SC-004)

### Implementation for User Story 4

- [X] T028 [US4] Apply `@limiter.limit("5/minute")` (the lifespan's Redis-backed `app.state.limiter`) to the `POST /auth/jwt/login` route in `app/auth/routes_auth.py`, reusing the spec-1 `RateLimitExceeded` handler (research D7, FR-010)

**Checkpoint**: All four user stories independently functional.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Docs, lint/format, validation, and coverage gates.

- [X] T029 [P] Update `docs/RUNBOOK.md` (auth setup + seed-admin step) and add a DECISIONS entry summarizing research D1–D13, including an explicit record that account **email is intentionally stored in `UserLoggedIn`/`LoginFailed` audit payloads** (account identifier, not patient PII — required for credential-stuffing/forensic investigation; passwords/hashes are never stored) — analyze finding L1, signed off 2026-06-06
- [X] T030 Run `uv run ruff check app worker tests scripts` AND `uv run black --check app worker tests scripts` — both MUST pass (lint authority)
- [X] T031 Execute `quickstart.md` scenarios 1–6 against the live Docker stack to validate end-to-end
- [X] T032 Confirm coverage gate in CI: ≥95% on the auth + DB-write paths and ≥80% overall (SC-007)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately.
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories. Internal order:
  T005/T009/T011 [P] → T006 → T007 → T008 (migration after both model changes) → T010 (after T009) → T012 (after T006, T011) → T013 (after T006, T012).
- **US1 (Phase 3)**: After Foundational. MVP.
- **US2 (Phase 4)**: After Foundational. Independent of US1 (guards reuse `current_active_user`).
- **US3 (Phase 5)**: After Foundational **and US2** (uses `require_admin`).
- **US4 (Phase 6)**: After Foundational **and US1** (decorates the login route).
- **Polish (Phase 7)**: After all targeted stories.

### Within Each User Story

- Tests are written first and expected to FAIL before implementation (constitution TDD intent).
- Models → manager/backend → routes → router registration.
- `app/main.py` and `app/auth/routes_auth.py` are shared files: US1 creates the login route,
  US4 modifies it; US1 and US3 each register a router in `main.py` — these are sequential
  (not [P]) to avoid merge conflicts.

### Parallel Opportunities

- Setup: T002, T003 [P] (T001 first; T004 after T002).
- Foundational: T005, T009, T011 [P] at the start.
- Each story's test tasks marked [P] run together before that story's implementation.
- With a team after Foundational: US1 and US2 in parallel (both P1); US4 starts once US1's
  login route exists; US3 starts once US2's `require_admin` exists.

---

## Parallel Example: Foundational kickoff

```bash
# After Setup, launch the independent foundational pieces together:
Task: "Add Role enum + schemas in app/auth/schemas.py"          # T005
Task: "Add 5 auth domain events in app/domain/events.py"        # T009
Task: "Add validate_password_policy helper in app/auth/manager.py"  # T011
```

## Parallel Example: User Story 1 tests

```bash
Task: "Integration test app login/token in tests/integration/test_auth_login.py"  # T015
Task: "Unit test schemas no-hash-leak in tests/unit/test_auth_schemas.py"         # T016
Task: "Unit test password policy in tests/unit/test_password_policy.py"           # T016b
```

---

## Implementation Strategy

### MVP First (US1 only)

1. Phase 1 Setup → 2. Phase 2 Foundational → 3. Phase 3 US1 → **STOP & VALIDATE** (login +
   protected-endpoint rejection). This is a demoable MVP: the platform now has authenticated
   identity.

### Incremental Delivery (honoring the <400-line PR rule)

1. Setup + Foundational → foundation ready (staged: schema/migration PR, then backend/manager PR).
2. US1 → test → demo (login works).
3. US2 → test → demo (role guards enforce 403).
4. US3 → test → demo (admin manages users, scoped + audited + bootstrap).
5. US4 → test → demo (login throttled).
6. Polish → lint/format, docs, quickstart validation, coverage gate.

### Notes

- [P] = different files, no incomplete dependencies; [Story] maps to spec.md user stories.
- Commit per task or logical group (Conventional Commits, NO Co-Authored-By trailer).
- Stop at any checkpoint to validate a story independently.
- Watch the shared files (`app/main.py`, `app/auth/routes_auth.py`) — keep their edits sequential.
