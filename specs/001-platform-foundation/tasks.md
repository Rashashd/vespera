---
description: "Task list for Platform Foundation & Security Skeleton"
---

# Tasks: Platform Foundation & Security Skeleton

**Input**: Design documents from `specs/001-platform-foundation/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/health.md

**Tests**: Included — the constitution mandates coverage gates (80% overall, 95%+ on audit
DB writes) and quickstart.md defines validation scenarios.

**Organization**: Tasks grouped by user story (US1–US5 from spec.md) for independent,
incremental delivery.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: User story the task serves (US1–US5); Setup/Foundational/Polish have no label

## Path Conventions

Modular monolith: backend under `app/`, worker under `worker/`, tests under `tests/`
(per plan.md Project Structure).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and toolchain

- [X] T001 Initialize `uv` project with dependencies (FastAPI, uvicorn, SQLAlchemy[async], asyncpg, alembic, redis, arq, hvac, pydantic-settings, structlog, sentry-sdk, secure, slowapi, tenacity) in `pyproject.toml`
- [X] T002 [P] Configure pre-commit with gitleaks + black + isort + ruff in `.pre-commit-config.yaml`
- [X] T003 [P] Configure pytest + pytest-asyncio + coverage settings in `pyproject.toml`
- [X] T004 [P] Create `app/` package tree with one-sentence module docstrings (core/, api/, domain/, db/, audit/, infra/) and `worker/`
- [X] T005 Author `docker-compose.yml` with services api, worker, vault (dev mode), postgres (pgvector image), redis — `VAULT_ADDR`/`VAULT_TOKEN` in `environment:` only, no secret values
- [X] T006 [P] Create `.env.example` documenting only `VAULT_ADDR` and `VAULT_TOKEN`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core scaffolding every user story depends on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T007 Implement `Settings` (pydantic-settings, `extra="forbid"`) with non-secret fields + empty secret fields + pinned model ids in `app/core/config.py`
- [X] T008 Implement structlog JSON configuration with `client_id`/`finding_id` binding and a secret/PII redaction processor in `app/observability/logging.py`
- [X] T009 [P] Implement async SQLAlchemy engine + session factory in `app/db/base.py`
- [X] T010 [P] Implement async Redis client factory in `app/infra/redis.py`
- [X] T011 [P] Implement in-process `EventDispatcher` (synchronous, dispatches within caller's DB session) in `app/core/dispatcher.py`
- [X] T012 [P] Implement domain event base + example frozen dataclasses (FindingClassified, ReportApproved, ClientErased) in `app/domain/events.py`
- [X] T013 Initialize Alembic (async `env.py`, `alembic.ini`) wired to `Settings.database_url` in `app/db/migrations/`
- [X] T014 Create FastAPI app factory and empty lifespan + router registration shell in `app/main.py` and `app/core/lifespan.py`

**Checkpoint**: App scaffolding boots an empty app; user stories can now proceed.

---

## Phase 3: User Story 1 - Stack boots safely or refuses to start (Priority: P1) 🎯 MVP

**Goal**: The app loads secrets first, validates dependencies, and refuses to boot on any
failure; the worker shares the identical bootstrap.

**Independent Test**: Bring the stack up healthy and hit `/health`; then disable Vault / DB /
Redis in turn and confirm the app refuses to boot with a specific error each time.

### Tests for User Story 1 ⚠️

- [X] T015 [P] [US1] Integration test: fresh-clone boot reaches healthy state in `tests/integration/test_boot.py`
- [X] T016 [P] [US1] Integration test: refuse-to-boot when Vault / Postgres / Redis unavailable, error names the cause, in `tests/integration/test_startup_failfast.py`
- [X] T017 [P] [US1] Unit test: `Settings` rejects an unknown/invalid field (SC-009) in `tests/unit/test_config.py`

### Implementation for User Story 1

- [X] T018 [US1] Implement `load_secrets_from_vault(settings)` (KV v2 `pantera/secrets`, required keys: database_url, redis_url, ≥1 LLM key; raise on unauth/unreachable/missing) in `app/core/startup.py`
- [X] T019 [US1] Implement `check_database`, `check_redis`, `check_model_artifacts` (hash check no-op when absent) + `run_startup_checks` in `app/core/startup.py`
- [X] T020 [US1] Implement LLM adapter `build_llm_client(settings)` selecting provider by available key in `app/infra/llm_adapter.py`
- [X] T021 [US1] Wire lifespan ordering (secrets → engine → redis → llm → checks → yield → dispose engine/close redis) in `app/core/lifespan.py`
- [X] T022 [US1] Implement shared `Depends()` providers (session, settings, redis) in `app/core/dependencies.py`
- [X] T023 [US1] Implement ARQ `WorkerSettings` skeleton (`on_startup`/`on_shutdown` reuse the same secret-load + engine/redis bootstrap, `functions=[]`, no cron, `handle_signals=True`) in `worker/worker.py`

**Checkpoint**: Stack boots healthy or fails fast; worker bootstraps identically. **MVP.**

---

## Phase 4: User Story 2 - Secrets never appear in repo, files, or logs (Priority: P1)

**Goal**: All real secrets live only in Vault; nothing leaks into the repo, history, files,
logs, or traces.

**Independent Test**: Run a secret scan over tree + history (0 findings) and confirm no
secret/PII appears in logs or traces.

### Tests for User Story 2 ⚠️

- [X] T024 [P] [US2] Unit test: log redaction processor drops secret/PII keys (SC-003) in `tests/unit/test_logging_redaction.py`
- [X] T025 [P] [US2] Integration/CI check: gitleaks scan of tree + history returns 0 findings in `tests/integration/test_secret_scan.py` (or CI job)

### Implementation for User Story 2

- [X] T026 [US2] Add one-time Vault secret-provisioning helper script in `scripts/write_secrets.py`
- [X] T027 [US2] Harden the structlog secret/PII redaction processor (deny-list of secret/PII keys) in `app/observability/logging.py`
- [X] T028 [US2] Wire gitleaks into CI (lint/scan job) in `.github/workflows/ci.yml`

**Checkpoint**: Secret scanning passes; logs are secret/PII-free.

---

## Phase 5: User Story 3 - Liveness and observability (Priority: P2)

**Goal**: A shallow public `/health` endpoint, Sentry error capture, and a Redis-backed
rate-limit capability.

**Independent Test**: Call `/health` (fast 200 `{"status":"ok"}`); raise an unhandled
exception and confirm Sentry capture; apply the limiter and confirm it rejects over-limit.

### Tests for User Story 3 ⚠️

- [X] T029 [P] [US3] Integration test: `GET /health` returns 200 `{"status":"ok"}`, minimal body, under latency target (SC-004) in `tests/integration/test_health.py`
- [X] T030 [P] [US3] Integration test: rate-limit capability rejects requests over the configured limit (SC-010) in `tests/integration/test_rate_limit.py`
- [X] T030a [P] [US3] Integration test: an unhandled exception is captured by Sentry (SC-005) in `tests/integration/test_sentry_capture.py`

### Implementation for User Story 3

- [X] T031 [US3] Implement public shallow `GET /health` route (pulled forward — US1 boot test needs it) in `app/api/health.py` and register it in `app/main.py`
- [X] T032 [US3] Initialize Sentry once at startup with `send_default_pii=False` (captures unhandled exceptions, no PII) in `app/observability/sentry.py`
- [X] T033 [US3] Construct Redis-backed slowapi `Limiter` capability on `app.state` (no login policy yet) in `app/observability/headers.py`

**Checkpoint**: Liveness + error capture + rate-limit capability working.

---

## Phase 6: User Story 4 - State changes are auditable via domain events (Priority: P2)

**Goal**: Every dispatched domain event writes exactly one append-only `audit_log` entry in
the same transaction as the originating change; audit-write failure rolls back the operation.

**Independent Test**: Dispatch an event → one audit row; force an audit-write failure → the
originating state change is rolled back.

### Tests for User Story 4 ⚠️

- [X] T034 [P] [US4] Integration test: one dispatched event → exactly one `audit_log` row (SC-006) in `tests/integration/test_audit.py`
- [X] T035 [P] [US4] Integration test: forced audit-write failure rolls back the originating change (FR-013a) in `tests/integration/test_audit_atomicity.py`

### Implementation for User Story 4

- [X] T036 [US4] Implement `audit_log` ORM model + `SYSTEM_ACTOR_ID = 0` constant (actor_id NOT NULL, actor_type human/system) in `app/db/models.py`
- [X] T037 [US4] Implement passive `audit_log_handler` writing in the caller's session in `app/audit/handler.py`
- [X] T038 [US4] Register dispatcher + audit handler at startup in `app/core/lifespan.py`
- [X] T039 [US4] Create Alembic baseline migration: enable `vector`/`pg_trgm` extensions + create `audit_log` with indexes in `app/db/migrations/versions/0001_baseline.py`

**Checkpoint**: Audit trail is atomic, append-only, and human/system attributed.

---

## Phase 7: User Story 5 - Persistence baseline & security headers (Priority: P3)

**Goal**: Security headers on all responses; a migration-managed baseline with tenant-ready
indexing conventions documented for later specs.

**Independent Test**: Inspect any response for the required headers; apply the baseline
migration to an empty DB and confirm `audit_log` + indexes exist.

### Tests for User Story 5 ⚠️

- [X] T040 [P] [US5] Integration test: required security headers present on responses (SC-007) in `tests/integration/test_headers.py`
- [X] T041 [P] [US5] Integration test: baseline migration on empty DB yields `audit_log` + indexes (SC-008) in `tests/integration/test_migration_baseline.py`

### Implementation for User Story 5

- [X] T042 [US5] Apply `secure` security-headers middleware (HSTS, X-Frame-Options: DENY, nosniff, Referrer-Policy, CSP `default-src 'self'`) in `app/main.py`
- [X] T043 [US5] Document tenant `client_id` + index conventions for later specs (no business tables created here) in `app/db/CONVENTIONS.md`

**Checkpoint**: Headers enforced; baseline schema + conventions in place.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [X] T044 Extend the CI pipeline created in T028 with lint, ruff (incl. async-correctness rules for FR-018), type-check, pytest, and coverage gates (80% overall / 95% audit path) in `.github/workflows/ci.yml`
- [X] T045 [P] Stub project docs referenced by the brief (`DECISIONS.md`, `RUNBOOK.md`, `SECURITY.md`) at repo root
- [X] T046 Run `quickstart.md` scenarios 1–7 end-to-end and record results (stack-free scenarios validated via pytest; full-stack scenarios 1/2/6 wired into CI + documented in RUNBOOK)
- [X] T047 [P] Verify all modules ≤ ~300 lines (longest is startup.py at 72) with one-sentence docstrings; refactor any that exceed

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies
- **Foundational (Phase 2)**: depends on Setup — BLOCKS all user stories
- **US1 (Phase 3)**: depends on Foundational — the MVP
- **US2 (Phase 4)**: depends on Foundational; pairs naturally with US1 (uses `load_secrets` + logging)
- **US3 (Phase 5)**: depends on Foundational; needs the app factory (T014) + observability module
- **US4 (Phase 6)**: depends on Foundational (dispatcher T011, db base T009, Alembic T013)
- **US5 (Phase 7)**: depends on Foundational; T041 (migration baseline test) depends on US4 T039
- **Polish (Phase 8)**: after all desired stories

### Cross-story notes

- US1–US5 each modify `app/main.py`/`lifespan.py` in small, additive ways — sequence those
  edits (not parallel) to avoid conflicts; the rest of each story is independent.
- `app/observability/` modules are added by T032 (sentry.py) and T033 (headers.py) in US3.
- US5's migration baseline test (T041) consumes the migration created in US4 (T039).

### Parallel Opportunities

- Setup: T002, T003, T004, T006 in parallel.
- Foundational: T009, T010, T011, T012 in parallel after T007/T008.
- Within each story, all `[P]` test tasks run together; models/independent files in parallel.

---

## Parallel Example: User Story 1

```bash
# Tests together:
Task: "Integration test: fresh-clone boot in tests/integration/test_boot.py"
Task: "Integration test: refuse-to-boot in tests/integration/test_startup_failfast.py"
Task: "Unit test: Settings rejects unknown field in tests/unit/test_config.py"
```

---

## Implementation Strategy

### MVP First (User Story 1)

1. Phase 1 Setup → 2. Phase 2 Foundational → 3. Phase 3 US1 → **STOP & VALIDATE** (boot
   healthy + fail-fast). This is a demoable MVP: the stack comes up from a fresh clone or
   refuses safely.

### Incremental Delivery

US1 (boot) → US2 (secret safety) → US3 (liveness/obs) → US4 (audit) → US5 (headers/baseline),
validating each independently against its success criteria before moving on.

---

## Notes

- [P] = different files, no incomplete dependencies.
- Verify each story's tests fail before implementing it.
- Commit after each task or logical group (Conventional Commits).
- Coverage gate: 80% overall, 95%+ on the audit DB-write path (T034/T035 cover it).
- Total: 48 tasks — Setup 6, Foundational 8, US1 9, US2 5, US3 6, US4 6, US5 4, Polish 4.
