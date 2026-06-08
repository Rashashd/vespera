# Quickstart & Validation: Authentication & Roles

Runnable scenarios that prove the feature end-to-end. Implementation details live in `tasks.md`
and the code; this is a validation/run guide. See `data-model.md` and `contracts/` for shapes.

## Prerequisites

- Spec-1 stack running: `docker compose up -d --wait vault postgres redis`
- Secrets written (now includes `auth_jwt_secret`, `bootstrap_admin_*`):
  `uv run python scripts/write_secrets.py` (needs an LLM key env var as before)
- Dependencies synced: `uv sync` (adds `fastapi-users[sqlalchemy]`)
- Migrations applied: `docker compose run --rm api alembic upgrade head` (applies `0002_auth`)
- Bootstrap the first admin (idempotent): `docker compose run --rm api python scripts/seed_admin.py`

## Scenario 1 — Authenticate (US1 / FR-001..003)

1. Log in as the seeded admin:
   ```bash
   curl -s -X POST localhost:8000/auth/jwt/login \
     -d "username=$ADMIN_EMAIL&password=$ADMIN_PASSWORD"
   ```
   **Expect** 200 with `{ "access_token": "...", "token_type": "bearer" }`.
2. Call a protected endpoint with the token → **2xx**; without it → **401**; with a tampered
   token → **401** (FR-003).
3. Log in with a wrong password → **400** `LOGIN_BAD_CREDENTIALS` (generic; same body whether the
   email exists or not — FR-002).

## Scenario 2 — Role authorization (US2 / FR-004..005)

1. As admin, create a reviewer (Scenario 3), obtain a reviewer token.
2. Reviewer calls an `admin`-only endpoint (e.g. `GET /users`) → **403** (authenticated but
   forbidden).
3. Admin calls the same endpoint → **2xx**.
4. Unauthenticated caller hits any guarded endpoint → **401** (checked before role).

   **Expect**: 401 (no token) and 403 (wrong role) are distinct (SC-002).

## Scenario 3 — Admin user management & tenant isolation (US3 / FR-006..008, 013, 014)

1. Admin creates a reviewer in their client:
   ```bash
   curl -s -X POST localhost:8000/users -H "Authorization: Bearer $ADMIN_TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"email":"rev@x.com","password":"Abcdef1!","role":"reviewer"}'
   ```
   **Expect** 201 `UserRead`; new user's `client_id` = admin's client.
2. `GET /users` returns only the admin's client's users (SC-003).
3. Deactivate the reviewer (`PATCH /users/{id}` `{"is_active": false}`) → 200; the reviewer can
   no longer log in (**400**), but their audit rows remain (FR-008).
4. Attempt to deactivate/demote the **last active admin** → **409 LAST_ADMIN** (FR-013).
5. Create a user with an email already in use → **409 USER_ALREADY_EXISTS** (global uniqueness).
6. (Isolation) With a client-B admin token, attempt to `PATCH` a client-A user → **404** (no
   cross-tenant reveal, SC-003).

## Scenario 4 — Login rate limiting (US4 / FR-010 / SC-004)

1. Fire 6 login attempts within 60s from one source:
   ```bash
   for i in $(seq 1 6); do curl -s -o /dev/null -w "%{http_code}\n" \
     -X POST localhost:8000/auth/jwt/login -d "username=x@x.com&password=wrong"; done
   ```
   **Expect**: first 5 → 400, the 6th → **429** (SC-004).
2. Wait for the window to reset → a fresh attempt is accepted again.

## Scenario 5 — Password policy (FR-016)

- Create a user with `"password":"weak"` → **400 PASSWORD_POLICY**.
- `"Abcdef1!"` (≥8, upper+lower+digit+symbol) → accepted.

## Scenario 6 — Audit trail (FR-012 / SC-006)

After running Scenarios 1–4, query `audit_log`:
- Exactly one row per security event (`UserLoggedIn`, `LoginFailed`, `UserCreated`,
  `UserRoleChanged`, `UserDeactivated`).
- Human events: `actor_type='human'`, `actor_id` = acting user, `actor_user_id` = same (FK set).
- Unknown-email failed login: `actor_type='system'`, `actor_id=0`, `actor_user_id` NULL.
- No password or hash appears in any payload (SC-005).

## Automated validation

```bash
# Stack-free unit tests (password policy, role guards, schemas)
uv run pytest tests/unit -q

# Full auth integration suite (needs the live stack)
$env:PANTERA_INTEGRATION=1; uv run pytest tests/integration/test_auth_login.py \
  tests/integration/test_authz.py tests/integration/test_users_admin.py \
  tests/integration/test_login_rate_limit.py tests/integration/test_auth_audit.py -q

# Lint + format gate (BOTH must pass)
uv run ruff check app worker tests scripts
uv run black --check app worker tests scripts
```

**Coverage gate**: auth + DB-write paths must reach ≥95% (SC-007); overall ≥80% in CI.
