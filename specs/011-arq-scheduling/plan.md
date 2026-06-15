# Implementation Plan: Durable ARQ Job Orchestration & Cron Scheduling

**Branch**: `011-arq-scheduling` | **Date**: 2026-06-15 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/011-arq-scheduling/spec.md`

> **READ FIRST before `/speckit-implement`:** [implementation-notes.md](./implementation-notes.md) — verified
> live-code anchors (exact signatures, file:line, what does NOT exist yet, patterns to copy). The
> anti-hallucination guide is mandatory; a cold implementer will otherwise hallucinate APIs/fields.

## Summary

Move the pipeline from in-process FastAPI `BackgroundTasks` to a durable ARQ queue (Redis broker) and
add an hourly cron scheduler that drives each watchlist's full cadence cycle end-to-end. The existing
stage runners (`run_ingestion`, `index_build_runner`, `triage_document_runner`, `draft_expedited`,
`redraft_report`, `consolidate_batch`) are wrapped as ARQ tasks with deterministic job IDs (idempotency),
bounded retry (3 tries) + dead-letter (new table + system-actor audit event + dashboard card), and
graceful drain. A new `watchlist_cycles` table tracks per-cycle state; the index step becomes
watchlist-scoped (`index_build_runs` gains `watchlist_id`, single-running guard → per-(client,watchlist)).
A `jobs_inline` setting runs jobs in-process for dev/tests (never prod). Merge gate: a reliability +
due-selection eval suite committed to `eval_thresholds.yaml`.

## Technical Context

**Language/Version**: Python 3.13 + uv

**Primary Dependencies**: ARQ ≥0.26 (already a dependency), Redis (asyncio client already used), FastAPI,
SQLAlchemy async + asyncpg, Alembic, structlog, tenacity. No new runtime dependency required.

**Storage**: PostgreSQL (new tables `watchlist_cycles`, `dead_letter`; additive columns on
`index_build_runs` and `watchlists`; migration **0010**, down_revision **0009**). Redis as the ARQ broker
(`redis_url` from Vault; `rediss://` TLS in prod).

**Testing**: pytest. New `tests/integration/test_scheduling_reliability.py` (the merge-gate suite) +
`tests/unit/` for due-selection and budget-policy logic. Integration needs `PANTERA_INTEGRATION=1` + the
compose stack; the reliability suite drives ARQ in **burst mode** (`worker.run_check` / direct coroutine
calls) and toggles `jobs_inline` to prove parity.

**Target Platform**: Linux server containers (API + ARQ worker share the image; worker entrypoint =
`arq worker.worker.WorkerSettings`).

**Project Type**: Modular monolith + separate ARQ worker process (constitution VI: worker is an allowed
separate container by execution model).

**Performance Goals**: Not latency-bound. Scheduler tick is hourly and cheap (one indexed scan). Job
throughput bounded by `worker_max_jobs`. The gate is correctness (idempotency/loss/retry/parity/
due-selection), not p95.

**Constraints**: Async throughout; tenacity on external calls (no retry on 4xx); `Settings`
`extra="forbid"`, no `os.getenv` outside `config.py`; structlog JSON, no PII/secrets; ≤~300 lines/file;
Conventional Commits, no Co-Authored-By; both ruff AND black.

**Scale/Scope**: Tens of clients × a few watchlists each; daily–monthly cadences; one coalesced catch-up
cycle after downtime. Dead-letter retention default 90 days.

## Constitution Check

*GATE: must pass before Phase 0 and re-checked after Phase 1.*

| Principle | Impact | Status |
|---|---|---|
| I. Human-in-the-Loop (NON-NEGOTIABLE) | Automation drafts/consolidates but **never sends**; reviewer gate untouched; nothing auto-approves (FR-024). | ✅ PASS |
| II. Grounding | No change to retrieval/drafting grounding; orchestration only. | ✅ PASS (N/A) |
| III. Triage Fails Safe | Budget `pause`/`critical_only` policies MUST still run serious-finding detection/escalation/alerting (FR-019b, SC-012). | ✅ PASS (explicitly enforced) |
| IV. Every Decision Backed by a Number | New `scheduling` block in `eval_thresholds.yaml` (due-selection precision/recall = 1.0; reliability invariants) gated in CI `eval` (FR-025, SC-011). | ✅ PASS |
| V. Multi-Tenant Isolation & Data Protection | Jobs carry `client_id`; suspended clients excluded from auto-scheduling (FR-013); dead-letter/audit free of PII (FR-011); system-actor events via the existing append-only audit log. | ✅ PASS |
| VI. Lean, Reproducible, Justified Architecture | Reuses the already-justified ARQ worker; no new broker; no MCP; no torch. | ✅ PASS |
| VII. Own Every Line | Spec-driven; implementation-notes pins every anchor. | ✅ PASS |

**Engineering standards:** async ✅; tenacity-on-externals preserved (job-level retry sits on top) ✅;
domain events + ARQ enqueue, no new broker ✅; worker uses `load_secrets_from_vault` in `on_startup` ✅;
structlog ✅; file-size discipline (split job modules per stage) ✅.

**No violations → Complexity Tracking is empty.** The one schema change to a prior spec
(`index_build_runs.watchlist_id`) is in-scope per a recorded clarification, not a complexity deviation.

## Project Structure

### Documentation (this feature)

```text
specs/011-arq-scheduling/
├── plan.md                  # This file
├── research.md              # Phase 0 — decisions (ARQ wrapping, idempotency, cron, parity)
├── data-model.md            # Phase 1 — migration 0010 (watchlist_cycles, dead_letter, index/watchlist cols)
├── quickstart.md            # Phase 1 — run worker + scheduler; reliability validation scenarios
├── contracts/
│   ├── jobs.md              # ARQ job catalog: names, args, deterministic job_id keys, retry classes
│   ├── scheduler.md         # cron tick → due-selection → cycle chain advancement
│   └── endpoints.md         # new/changed HTTP: budget-policy set, dead-letter list, cycle status
├── implementation-notes.md  # READ FIRST — verified anchors, what doesn't exist, patterns to copy
└── checklists/              # requirements.md (spec-quality) + release-gate.md (already present)
```

### Source Code (repository root)

```text
app/
├── jobs/                       # NEW — durable orchestration layer (thin wrappers; no stage logic)
│   ├── __init__.py
│   ├── enqueue.py              # enqueue helper: ARQ enqueue OR inline (jobs_inline); deterministic job_id
│   ├── context.py              # WorkerContext shim exposing settings/session_factory/redis/dispatcher
│   ├── tasks.py                # ARQ task functions wrapping each stage runner (+ chain advancement)
│   ├── retry.py                # transient-vs-permanent classification; PermanentJobError
│   ├── dead_letter.py          # persist dead-letter row + dispatch JobDeadLettered (system actor)
│   └── scheduler.py            # hourly cron: due-selection + start cycle
├── scheduling/                 # NEW — cycle domain (state machine, due-ness, budget policy)
│   ├── __init__.py
│   ├── models.py               # WatchlistCycle, DeadLetter ORM
│   ├── service.py              # cycle create/advance/fail/complete; due-watchlist query
│   ├── due.py                  # cadence interval math (UTC) — unit-testable, the golden-set core
│   └── budget_policy.py        # over-budget gate per budget_exceeded_policy (Constitution III safe)
├── reports/, ingestion/, embedding/, triage/   # routes: replace BackgroundTasks.add_task → jobs.enqueue
├── clients/                    # watchlists: add budget_exceeded_policy field + admin set endpoint
└── core/config.py              # add jobs_inline + worker/scheduler/dead-letter settings

worker/worker.py                # register real ARQ functions + cron; build dispatcher + session_factory;
                                # register_audit_handlers; rediss:// from settings (NOT host="redis")

app/db/migrations/versions/0010_scheduling.py   # watchlist_cycles, dead_letter, index/watchlist columns

tests/
├── unit/test_due_selection.py          # cadence due-ness (golden-set logic)
├── unit/test_budget_policy.py          # policy gate + Constitution III invariant
└── integration/test_scheduling_reliability.py  # MERGE GATE: idempotency/retry/DLQ/drain/parity/chain
eval/scheduling/run_due_selection_eval.py        # due-selection golden set → precision/recall=1.0
eval_thresholds.yaml                              # + scheduling: {...}
```

**Structure Decision**: A new `app/jobs/` package owns durability/orchestration (enqueue, retry, dead-letter,
worker context, ARQ task wrappers, scheduler) and a new `app/scheduling/` package owns the cycle domain
(models, state service, due-ness, budget policy). Stage runners are untouched except the deliberate
watchlist-scoping of `index_build_runner`. Routes change only their trigger call (`add_task` → `enqueue`).
This keeps durability concerns out of stage logic and respects the ≤300-line file rule.

## Phase 0 / 1 status

- Phase 0 → `research.md` (10 decisions; no open NEEDS CLARIFICATION — spec clarifications resolved them).
- Phase 1 → `data-model.md`, `contracts/*`, `quickstart.md`, agent-context pointer updated.

## Complexity Tracking

*No constitution violations — table intentionally empty.*
