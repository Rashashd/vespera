# Implementation Plan: Platform Foundation & Security Skeleton

**Branch**: `001-platform-foundation` | **Date**: 2026-06-06 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-platform-foundation/spec.md`

## Summary

Stand up Pantera's operational and security spine: a one-command Docker Compose stack
(API + worker skeleton + Vault + Postgres + Redis) where the FastAPI application loads all
secrets from Vault into memory as the first lifespan step, validates critical dependencies
and refuses to boot on failure, initializes shared singletons once, exposes a shallow
public liveness endpoint, emits structured JSON logs and captures unhandled exceptions in
Sentry, applies security headers, provides a Redis-backed rate-limit capability, and runs
an in-process domain-event dispatcher whose passive audit listener writes one append-only
`audit_log` row per event in the same transaction as the originating change. Persistence
starts from an Alembic baseline with tenant-ready indexing.

## Technical Context

**Language/Version**: Python 3.12 (managed by `uv`)

**Primary Dependencies**: FastAPI, Uvicorn, SQLAlchemy 2.x (async) + asyncpg, Alembic,
redis-py (async), ARQ, hvac, pydantic-settings, structlog, sentry-sdk, `secure`, slowapi,
tenacity

**Storage**: PostgreSQL 16 (+ `pgvector` extension enabled at baseline for later features);
Redis 7 (cache, rate-limit counters, ARQ broker)

**Testing**: pytest + pytest-asyncio + httpx AsyncClient; integration tests against the
Compose stack (Postgres, Redis, Vault dev)

**Target Platform**: Linux containers via Docker Compose (local); managed PaaS + managed
Postgres/Redis (later deployment feature)

**Project Type**: Web service — modular monolith backend (`app/`) plus a justified separate
worker container (`worker/`); frontend is a later feature

**Performance Goals**: Health endpoint p99 well under 1s (SC-004); foundation carries no
high-throughput path

**Constraints**: Async throughout (no `requests`, no `time.sleep`); secrets only in Vault,
never on disk or in logs; fail-fast startup; non-secret config in one `extra="forbid"`
settings object; no `os.getenv()` outside `config.py`; files ≤ ~300 lines with a one-line
module docstring

**Scale/Scope**: Single API instance + single worker instance at capstone scale; horizontal
scaling out of scope

**Unknowns**: None remaining — the spec was clarified across two sessions and a formal
checklist gate (46/48); the 2 accepted plan-level items are resolved in
[research.md](./research.md)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Relevance to this feature | Status |
|-----------|---------------------------|--------|
| I. Human-in-the-Loop Authority | No send/draft paths in foundation | N/A |
| II. Grounding Is the Grade | No report/claim generation here | N/A |
| III. Triage Fails Safe | No triage logic here | N/A |
| IV. Every Decision Backed by a Number | Foundation outcomes are SC-measured (boot, latency, headers); no model decisions | PASS |
| V. Multi-Tenant Isolation & Data Protection | `client_id` baseline + indexes (FR-015); PII/secret exclusion from logs (FR-008) | PASS |
| VI. Lean, Reproducible, Justified Architecture | Modular monolith; justified containers (app, worker, Vault, Postgres, Redis); no torch; no MCP; `uv` lockfile | PASS |
| VII. Own Every Line (Spec-Driven) | Spec → clarify → checklist → plan; ≤300-line files; Conventional Commits | PASS |
| Security & Secrets | Core of this feature — Vault-only secrets, fail-fast, headers, rate-limit, secret scanning | PASS |
| Engineering Standards | Async, pydantic boundaries, structlog, tenacity, config discipline, atomic audit | PASS |

**Result**: PASS — no violations. Complexity Tracking left empty.

**Post-Design Re-check**: PASS — the data model and contracts introduce no new services,
no torch, no MCP, and keep secrets in Vault; atomic audit (FR-013a) is satisfied by the
in-transaction dispatcher design.

## Project Structure

### Documentation (this feature)

```text
specs/001-platform-foundation/
├── spec.md              # Feature specification (clarified)
├── plan.md              # This file
├── research.md          # Phase 0 — decisions & rationale
├── data-model.md        # Phase 1 — audit_log + baseline schema
├── quickstart.md        # Phase 1 — runnable validation scenarios
├── contracts/
│   └── health.md        # Phase 1 — /health endpoint contract
└── checklists/
    ├── requirements.md  # spec-quality checklist
    └── foundation.md    # requirements-quality gate (46/48)
```

### Source Code (repository root)

```text
app/
  main.py                # creates FastAPI app, attaches lifespan, registers routers
  core/
    config.py            # pydantic-settings Settings (extra="forbid") — non-secret + empty secret fields
    lifespan.py          # ordered startup (secrets → engine → redis → llm → checks) and shutdown
    startup.py           # load_secrets_from_vault() + check_database/redis/model_artifacts
    dependencies.py      # shared Depends() — session, settings, redis
    dispatcher.py        # in-process EventDispatcher (sync, in-transaction)
  observability/
    logging.py           # structlog config + client_id/finding_id binding + redaction
    sentry.py            # (US3) sentry init
    headers.py           # (US3/US5) security-headers middleware + slowapi limiter
  api/
    health.py            # GET /health → {"status":"ok"} (public, shallow)
  domain/
    events.py            # typed domain event dataclasses (base + examples)
  db/
    base.py              # async engine/session factory
    models.py            # SQLAlchemy ORM — audit_log
    migrations/          # Alembic baseline (env.py + initial revision)
  audit/
    handler.py           # passive audit_log_handler registered at startup
worker/
  worker.py              # ARQ WorkerSettings skeleton — startup/shutdown bootstrap, no jobs
docker-compose.yml       # api + worker + vault(dev) + postgres + redis; VAULT_ADDR/TOKEN only
.env.example             # documents VAULT_ADDR + VAULT_TOKEN only
pyproject.toml           # uv-managed deps + lockfile
.pre-commit-config.yaml  # gitleaks + black + isort + ruff
alembic.ini
tests/
  unit/                  # config, dispatcher, logging redaction
  integration/           # startup fail-fast, /health, audit atomicity, headers
```

**Structure Decision**: Modular monolith under `app/` with a single justified separate
`worker/` container (different execution model). Vault, Postgres, and Redis are
infrastructure containers. This matches Constitution VI and the brief's §4.7 architecture.

## Phase 0 & 1 Outputs

- Phase 0 → [research.md](./research.md) (all decisions resolved, no open NEEDS CLARIFICATION)
- Phase 1 → [data-model.md](./data-model.md), [contracts/health.md](./contracts/health.md),
  [quickstart.md](./quickstart.md); agent context (`CLAUDE.md`) updated to reference this plan

## Complexity Tracking

> No Constitution Check violations — no entries required.
