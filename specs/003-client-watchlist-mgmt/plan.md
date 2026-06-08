# Implementation Plan: Client & Watchlist Management

**Branch**: `003-client-watchlist-mgmt` | **Date**: 2026-06-06 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/003-client-watchlist-mgmt/spec.md`

## Summary

Give the platform a first-class `clients` (tenant) record and the per-watchlist monitoring
configuration that drives every later spec: named watchlists (1:many per client) holding
drugs / MeSH terms / keywords, plus per-watchlist cadence, severity threshold, and a recurring
monthly cost budget with a warn→soft-cap rule. Backend/API only (the React Admin Console is a
later slice). The work reuses spec-1/spec-2 foundations (async SQLAlchemy + Alembic, the
in-process domain-event dispatcher + passive audit handler, the `require_admin` /
`current_active_user` guards) and adds one Alembic migration that also reconciles the existing
bare `users.client_id` integers into real client rows and strengthens it to a foreign key.

## Technical Context

**Language/Version**: Python 3.13 (managed by `uv`)

**Primary Dependencies**: FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2, fastapi-users
(reused for the auth guards only). **No new runtime dependencies, no new external services, no
new Vault secrets.**

**Storage**: PostgreSQL (the existing pgvector image); new tables `clients`, `watchlists`,
`watchlist_items`, `watchlist_budget_usage`; a new FK `users.client_id → clients.id`.

**Testing**: `uv run pytest` (unit + integration); integration tests need
`PANTERA_INTEGRATION=1` + the live stack (see [dev-environment](../../memory/dev-environment.md)).

**Target Platform**: Linux container (api service in the existing docker-compose modular monolith).

**Project Type**: Web service (modular monolith) — backend only this spec.

**Performance Goals**: Configuration CRUD only; no throughput target beyond standard API
responsiveness. Tables are low-volume (clients, watchlists, items per tenant).

**Constraints**: Async throughout; Pydantic-validated boundaries (no ORM objects returned);
structured logging with `client_id` bound; every file ≤ ~300 lines with a one-sentence module
docstring; config-write paths ≥ 95% line coverage; overall suite ≥ 80% (CI gate).

**Scale/Scope**: Small. Order of tens of watchlists per client, a handful of items each.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Relevance | Status |
|-----------|-----------|--------|
| I. Human-in-the-Loop | No drafting/sending here | ✅ N/A |
| II. Grounding | No reports/claims here | ✅ N/A |
| III. Triage Fails Safe | Severity threshold default `serious` (escalate serious-and-above); levels are transparent named ICH-aligned values, not opaque scores | ✅ Aligned |
| IV. Backed by a Number | No model/eval here; the 95% write-path + 80% overall coverage gates apply | ✅ Aligned |
| V. Multi-Tenant Isolation (NON-NEGOTIABLE) | Core of this spec: every new table carries `client_id` and is indexed; all reads/writes client-scoped; cross-tenant access refused (404/no-reveal) | ✅ Enforced |
| VI. Lean, Reproducible, Justified | No new container, no torch, no MCP, no new dep; one new Alembic migration; one new `app/clients/` package | ✅ Aligned |
| VII. Own Every Line (Spec-Driven) | spec → clarify → checklist → plan → tasks → implement; Conventional Commits, PR < 400 lines | ✅ Aligned |

**Engineering standards applied**: async routes/queries; `tenacity`/HTTP retries N/A (no external
calls); Pydantic schemas at the boundary; `structlog` with `client_id` bound; new tables use
CHECK constraints for small enums (matching the spec-2 `ck_users_role` pattern); audit rows
written in the same transaction as the change via the existing dispatcher.

**Result**: PASS — no violations. Complexity Tracking table intentionally empty.

## Project Structure

### Documentation (this feature)

```text
specs/003-client-watchlist-mgmt/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── clients.md
│   └── watchlists.md
├── checklists/
│   ├── requirements.md          # spec-quality gate (from /speckit-specify)
│   └── requirements-quality.md  # requirements QA (from /speckit-checklist)
└── tasks.md             # /speckit-tasks output (NOT created here)
```

### Source Code (repository root)

New `app/clients/` package (mirrors the spec-2 `app/auth/` layout), one Alembic migration, an
operator seed script, and tests. No changes to existing modules except additive event classes
and router registration in `main.py`.

```text
app/
├── clients/                       # NEW package owned by this spec
│   ├── __init__.py
│   ├── enums.py                   # Cadence, SeverityLevel, WatchlistItemType, ClientStatus (reused by spec 8/11)
│   ├── models.py                  # Client, Watchlist, WatchlistItem, WatchlistBudgetUsage ORM
│   ├── schemas.py                 # Pydantic request/response (no ORM leakage)
│   ├── service.py                 # budget-state derivation, validation, queries (keeps routes thin)
│   ├── routes_clients.py          # GET/PATCH /clients/me (own client)
│   └── routes_watchlists.py       # /watchlists CRUD + items + per-watchlist config
├── domain/events.py               # ADD client/watchlist domain events (auto-audited)
├── db/migrations/versions/
│   └── 0003_clients_watchlists.py # NEW: tables + reconcile users.client_id + FK
└── main.py                        # ADD include_router(clients_router, watchlists_router)

scripts/
└── seed_client.py                 # NEW operator path: onboard/suspend a client (gitignored-secret-free)

tests/
├── unit/
│   ├── test_clients_schemas.py    # schema validation, budget-state derivation
│   └── test_budget_state.py       # warn/soft-cap/reset boundary logic (pure)
└── integration/
    ├── test_clients.py            # client record + reconciliation + /clients/me scoping
    ├── test_watchlists.py         # create/list/rename/deactivate, items idempotency, empty-reject
    ├── test_watchlist_config.py   # cadence/severity validation + defaults
    ├── test_watchlist_budget.py   # warning, soft-cap, sibling isolation, month reset
    ├── test_clients_authz.py      # admin-write / reviewer-view / cross-tenant refusal
    └── test_migration_0003.py     # reconciliation + FK integrity on upgrade/downgrade
```

**Structure Decision**: Follow the spec-2 precedent exactly — a self-contained feature package
under `app/clients/` with `models`/`schemas`/`service`/`routes_*`, thin routers delegating to a
`service.py`, small enums as CHECK constraints, and one additive Alembic migration. Client
*onboarding* (create/suspend a tenant) uses an operator script (`scripts/seed_client.py`),
mirroring the spec-2 `seed_admin.py` precedent and avoiding an admin self-lockout; ongoing
per-client/per-watchlist configuration uses the client-scoped admin API.

## Complexity Tracking

> No constitution violations — table intentionally empty.
