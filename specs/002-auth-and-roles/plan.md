# Implementation Plan: Authentication & Roles

**Branch**: `002-auth-and-roles` | **Date**: 2026-06-06 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/002-auth-and-roles/spec.md`

## Summary

Establish identity and authorization for the platform: email+password authentication issuing
short-lived (~30 min) stateless JWT access tokens, two roles (`admin`, `reviewer`), reusable
role guards, client-scoped admin user management, login rate limiting (5/min/IP), and audit
logging of all security events. Built on the spec-1 foundation (Vault secrets, async SQLAlchemy,
domain-event dispatcher + passive audit log, Redis-backed slowapi limiter). Auth is implemented
with **fastapi-users** (JWT strategy, argon2 hashing) wrapped in thin custom routes so we can
attach the rate limiter and emit audit domain events. A new Alembic migration adds the `users`
table and a nullable `actor_user_id` FK on `audit_log` for human-actor attribution.

## Technical Context

**Language/Version**: Python 3.13 (uv-managed; `requires-python >=3.12`)

**Primary Dependencies**: FastAPI, fastapi-users[sqlalchemy] (JWT auth, password hashing),
SQLAlchemy 2.0 async + asyncpg, Alembic, slowapi (Redis-backed, already wired), pydantic v2,
structlog, hvac (Vault). New runtime dependency: `fastapi-users[sqlalchemy]`.

**Storage**: PostgreSQL (pgvector image). New `users` table; new `actor_user_id` column on
`audit_log`. Migrations via Alembic (new `0002_auth` revision on top of `0001` baseline).

**Testing**: pytest + pytest-asyncio + httpx. Unit (stack-free) + integration (gated by
`PANTERA_INTEGRATION=1` with live Postgres/Redis/Vault). Constitution: 95%+ coverage on the
auth and DB-write paths; ≥80% overall.

**Target Platform**: Linux container (modular monolith API), same image as spec-1.

**Project Type**: Web service (FastAPI modular monolith). No frontend in this spec (Admin
Console UI is spec 3).

**Performance Goals**: Login p95 < 300 ms (excludes deliberate hashing cost); token validation
is stateless/in-process (loads the user once per request). B2B scale: tens–hundreds of users
per client.

**Constraints**: Async throughout; no secrets in `.env` (JWT secret from Vault); validated
pydantic boundaries (never return ORM objects); files ≤ ~300 lines with one-sentence module
docstrings; passwords/hashes never logged or returned.

**Scale/Scope**: Single new domain module (`app/auth/`), one migration, one seed script, 2
router groups (auth + admin users), 5 new domain events. Estimated > 400 lines total → staged
across multiple commits/PRs to honor the constitution PR-size rule (see Complexity Tracking).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Relevance & Compliance | Status |
|-----------|------------------------|--------|
| I. Human-in-the-Loop Authority | `reviewer` is defined as the send-authorizing role; this spec declares the role and guards but implements NO send/approval path (deferred to spec 10). No bypass introduced. | ✅ Pass |
| II. Grounding Is the Grade | No report/claim generation in this spec. | N/A |
| III. Triage Fails Safe | No triage in this spec. | N/A |
| IV. Every Decision Backed by a Number | Auth has no golden-set metric; the committed numbers are the 95%+ coverage gate on the auth/DB-write path and the rate-limit policy (5/min). | ✅ Pass |
| V. Multi-Tenant Isolation (NON-NEGOTIABLE) | Every `users` row carries `client_id` (indexed). All user-management/listing queries are client-scoped at the repository layer; cross-client read/modify refused; global email uniqueness keeps login deterministic. | ✅ Pass (by design) |
| VI. Lean, Reproducible, Justified Architecture | fastapi-users is a vetted async auth library (reduces hand-rolled crypto risk — aligns with "own every line" by not inventing auth primitives). No new container, no torch, no MCP. Managed by uv. | ✅ Pass |
| VII. Own Every Line / Spec-Driven | Spec → clarify → checklist → plan → tasks flow followed; Conventional Commits; every line defensible. PR-size (<400 lines) addressed via staged commits. | ✅ Pass |
| Security & Secrets | JWT signing secret loaded from Vault (new `auth_jwt_secret`), added to required-secret fail-fast set; login rate-limited; security headers already applied; no guardrails needed (no LLM calls). | ✅ Pass |
| Engineering Standards | Async routes/DB; pydantic schemas at boundaries (no ORM leakage); structlog binding `client_id`/`user_id`, never password; auth events via dispatcher → passive audit; files ≤300 lines. | ✅ Pass |

**Initial gate: PASS.** No unjustified violations. The only flagged item is PR size (process,
not architecture) — tracked in Complexity Tracking.

**Post-design re-check (after Phase 1): PASS.** The data model, contracts, and quickstart
introduce no new violations: tenant isolation is enforced at the repository layer (Principle V),
the JWT secret stays in Vault with fail-fast boot (Security), no LLM/guardrails surface is added,
and the new files are scoped one-purpose ≤300 lines. The three Complexity Tracking items remain
the only justified deviations.

## Project Structure

### Documentation (this feature)

```text
specs/002-auth-and-roles/
├── plan.md              # This file
├── research.md          # Phase 0 — decisions D1–D13
├── data-model.md        # Phase 1 — User entity, audit FK, role enum, lifecycle
├── quickstart.md        # Phase 1 — runnable validation scenarios
├── contracts/           # Phase 1 — auth + admin-users API contracts
│   ├── auth.md
│   └── users.md
├── checklists/
│   ├── requirements.md  # spec quality (16/16)
│   └── security.md      # security release gate (36 items)
└── tasks.md             # Phase 2 — created by /speckit-tasks (NOT here)
```

### Source Code (repository root)

```text
app/
├── auth/                        # NEW — auth & roles domain module
│   ├── __init__.py
│   ├── models.py                # User ORM (BigInteger PK, client_id, role, is_active, hashed_password)
│   ├── schemas.py               # UserRead / UserCreate / UserUpdate pydantic; Role enum
│   ├── manager.py               # UserManager: password policy (FR-016) + lifecycle event emission
│   ├── backend.py               # JWT strategy (Vault secret, 1800s), BearerTransport, FastAPIUsers wiring
│   ├── dependencies.py          # current_active_user, require_role(), require_admin, require_reviewer
│   ├── routes_auth.py           # POST /auth/jwt/login (rate-limited + audited), /logout
│   └── routes_users.py          # admin user mgmt (client-scoped, last-admin guard, audited)
├── domain/events.py             # MODIFY — add 5 auth domain events
├── db/models.py                 # MODIFY — add nullable actor_user_id FK to AuditLog
├── db/migrations/versions/
│   └── 0002_auth.py             # NEW — users table + audit_log.actor_user_id
├── core/config.py               # MODIFY — add auth_jwt_secret + token TTL setting
├── core/startup.py              # MODIFY — load auth_jwt_secret; add to required secrets
└── main.py                      # MODIFY — include auth + users routers; apply login limiter

scripts/
└── seed_admin.py                # NEW — one-time operator bootstrap (Vault-sourced, idempotent)

tests/
├── unit/
│   ├── test_password_policy.py  # FR-016 validation (stack-free)
│   ├── test_role_guards.py      # require_admin/reviewer 401 vs 403
│   └── test_auth_schemas.py     # schema validation, no-hash-leak
└── integration/
    ├── test_auth_login.py       # login success/fail, token accept/reject, deactivated user
    ├── test_authz.py            # role matrix across guarded endpoints
    ├── test_users_admin.py      # create/list/deactivate, client scoping, last-admin guard, escalation
    ├── test_login_rate_limit.py # 5/min/IP throttle + reset
    └── test_auth_audit.py       # one audit row per security event, correct attribution + FK
```

**Structure Decision**: A single new domain package `app/auth/` mirrors the spec-1 layout
(`app/audit/`, `app/observability/`) — one module per concern, each file ≤300 lines with a
one-sentence docstring. Auth lives in the modular monolith (no new container, per Constitution
VI). The new migration follows `app/db/CONVENTIONS.md` (its own revision, `client_id` indexed,
no ad-hoc DDL). Domain events extend the existing `app/domain/events.py` so the passive audit
handler auto-registers them (it walks `DomainEvent.__subclasses__()`).

## Complexity Tracking

| Item | Why Needed | Note / Mitigation |
|------|-----------|-------------------|
| New dependency `fastapi-users` | Mature, async, JWT + password-hashing auth; safer than hand-rolling crypto and explicitly named in the approved build plan. | Pinned via uv lockfile; only the auth backend + user-db adapter are used, routes are thin custom wrappers. Not a constitution violation. |
| Total change > 400 lines | Auth spans model, migration, backend, two router groups, seed, and tests. | Stage into ordered commits/PRs (model+migration → backend+manager → auth routes+rate-limit → admin users → audit wiring → tests) so each PR stays under the 400-line limit. Tracked here, resolved in `/speckit-tasks`. |
| New nullable `actor_user_id` column (vs reusing `actor_id`) | Clarification requires a nullable FK to `users.id` while the non-null `actor_id` sentinel (0) stays unlinked and spec-1 audit behavior is unbroken. | A separate nullable FK column is the only non-breaking way to add referential integrity without violating the existing `actor_id NOT NULL` + sentinel convention. See research D5. |
