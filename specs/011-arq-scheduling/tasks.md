# Tasks: Durable ARQ Job Orchestration & Cron Scheduling

**Feature**: `011-arq-scheduling` | **Branch**: `011-arq-scheduling`
**Inputs**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md)

> **READ FIRST**: [implementation-notes.md](./implementation-notes.md) — verified live-code anchors, the
> five trigger sites (incl. the `asyncio.create_task` one at `triage_trigger.py:85`), the worker
> dispatcher/audit gotcha, and everything that does NOT exist yet. Do not implement without it.

**Tests**: IN SCOPE — the reliability + due-selection suite is the committed merge gate (FR-025, SC-011).

**Conventions**: async throughout; tenacity on external calls (no retry on 4xx); `Settings`
`extra="forbid"`; structlog JSON, no PII/secrets; files ≤~300 lines; Conventional Commits, NO
Co-Authored-By; BOTH `ruff` and `black` must pass.

---

## Phase 1: Setup

- [X] T001 Add scheduling/worker settings to `app/core/config.py` (`jobs_inline=False`, `worker_max_jobs=10`, `worker_job_timeout=600`, `worker_shutdown_grace_seconds=600`, `scheduler_tick_cron_minute=0`, `dead_letter_retention_days=90`) — defaults only, no secrets (see implementation-notes §5)
- [X] T002 [P] Add a `scheduling:` block to `eval_thresholds.yaml` (`due_selection_precision_min/recall_min=1.0`, `duplicate_rate_max=0`, `loss_rate_max=0`, `transient_retry_recovery_min=1.0`, `inline_vs_durable_parity_min=1.0`)
- [X] T003 [P] Create package skeletons `app/jobs/__init__.py` and `app/scheduling/__init__.py` (module docstrings only)

## Phase 2: Foundational (BLOCKS all user stories)

- [X] T004 Create migration `app/db/migrations/versions/0010_scheduling.py` (`down_revision="0009"`): new tables `watchlist_cycles` + `dead_letter`; ALTER `index_build_runs` (+`watchlist_id` nullable FK, swap `uq_index_build_runs_client_running` → `uq_index_build_runs_client_wl_running` on `(client_id, watchlist_id) WHERE status='running'`); ALTER `watchlists` (+`budget_exceeded_policy` default `'continue'` + CHECK) — full schema in data-model.md; copy partial-unique pattern from `0006_chunks_index_state.py:127`; include a real `downgrade()`
- [X] T005 [P] Add `WatchlistCycle` + `DeadLetter` ORM models in `app/scheduling/models.py` (match migration columns + CHECK enums)
- [X] T006 [P] Add `budget_exceeded_policy` mapped column to `Watchlist` in `app/clients/models.py`
- [X] T007 [P] Add `watchlist_id` mapped column to `IndexBuildRun` (locate model via implementation-notes; same module as the index-run ORM)
- [X] T008 [P] Add `JobDeadLettered` + `WatchlistBudgetThresholdReached` frozen-dataclass events to `app/domain/events.py` (base `DomainEvent`; system convention `actor_id=0, actor_type="system"`)
- [X] T009 Wire worker bootstrap in `worker/worker.py` `startup(ctx)`: build `EventDispatcher()`, call `register_audit_handlers(dispatcher)`, build `create_session_factory(engine)`, stash both on `ctx`; replace `RedisSettings(host="redis",...)` with `RedisSettings.from_dsn(settings.redis_url)` (TLS-capable, FR-023) — see implementation-notes §3/§4 (the audit gotcha)
- [X] T010 [P] Implement `WorkerContext` shim in `app/jobs/context.py` exposing `.settings/.session_factory/.redis/.dispatcher/.llm` (duck-types `app.state`) built from ARQ `ctx`
- [X] T011 Build the app-side ARQ pool: create the pool from `RedisSettings.from_dsn(settings.redis_url)` in `app/core/lifespan.py`, stash on `app.state.arq`, dispose on shutdown

**Checkpoint**: schema + models + events + worker context exist; nothing wired to behavior yet.

---

## Phase 3: User Story 1 — Durable, idempotent execution (Priority: P1) 🎯 MVP

**Goal**: All pipeline work runs as durable, idempotent, retried, dead-lettered jobs that survive restarts
and drain on shutdown; in-prod ARQ, inline for dev/tests with parity.

**Independent test**: trigger each stage; kill/restart worker mid-job → completes once; re-enqueue → runs
once; transient error → retry-then-success; permanent error → no retry → dead-letter; SIGTERM → drains.

- [X] T012 [P] [US1] Reliability test suite scaffolding `tests/integration/test_scheduling_reliability.py`: idempotency (re-enqueue runs once), retry-then-succeed, permanent-no-retry, dead-letter-on-exhaustion, graceful-drain, inline-vs-durable parity (drive ARQ in burst/direct mode; toggle `jobs_inline`)
- [X] T013 [US1] Implement `PermanentJobError` + transient/permanent classification in `app/jobs/retry.py`
- [X] T014 [US1] Implement `enqueue(name, *, job_id, **args)` in `app/jobs/enqueue.py`: ARQ `enqueue_job(_job_id=...)` in prod, `await` coroutine when `Settings.jobs_inline`, surface broker-down to caller (FR-002a), never silent-drop/inline-in-prod
- [X] T015 [US1] Implement dead-letter recording in `app/jobs/dead_letter.py`: insert `dead_letter` row (non-PII args digest) + dispatch `JobDeadLettered` (system actor → audit) on retry exhaustion / `PermanentJobError`
- [X] T016 [US1] Implement ARQ task wrappers in `app/jobs/tasks.py` for `task_run_ingestion`, `task_index_build`, `task_redraft`, `task_expedited` (re-query ingestion watchlist items in-worker per implementation-notes §3; deterministic job_ids per contracts/jobs.md; retry/dead-letter via T013–T015)
- [X] T017 [US1] Register functions + `max_jobs`/`job_timeout`/shutdown grace from settings in `worker/worker.py` `WorkerSettings` (replace `heartbeat` placeholder)
- [X] T018 [P] [US1] Convert call site 1 — `app/ingestion/routes_ingestion.py:84` `background_tasks.add_task(run_ingestion,...)` → `enqueue("task_run_ingestion", job_id="ingest:{run_id}", ...)`
- [X] T019 [P] [US1] Convert call site 2 — `app/embedding/routes.py:67` `_run_index_build_background` → `enqueue("task_index_build", ...)`. ⚠️ This is the **client-wide manual** build: pass `watchlist_id=None`, job_id `index:{client_id}:manual:{run_id}` (distinct from the watchlist-scoped cycle build in T033; do NOT pass a cycle_id or watchlist scope here — G2)
- [X] T020 [P] [US1] Convert call site 3 — `app/reports/routes.py:166` redraft → `enqueue("task_redraft", job_id="redraft:{report_id}:{revision}", ...)`
- [X] T021 [P] [US1] Convert call site 4 — `app/reports/routes.py:343` manual expedited → `enqueue("task_expedited", job_id="expedited:{finding_id}:{revision}", ...)`
- [X] T022 [US1] Convert call site 5 — `app/embedding/triage_trigger.py:85` `asyncio.create_task(draft_expedited(...))` → `enqueue("task_expedited", ...)` (the auto fan-out; pass a WorkerContext/app_state — this runs inside the index job)
- [X] T023 [US1] Add prod-guard startup assertion in `app/core/lifespan.py`: `jobs_inline` must be False unless an explicit dev marker is set (SC-008)
- [X] T024 [US1] Verify/wire graceful drain (`handle_signals` + grace) and confirm in-flight work is left re-runnable, not falsely complete (covered by T012 drain case)
- [X] T024a [US1] Make the startup ingestion-run reconciliation ARQ-aware (`app/core/lifespan.py:34-44` `reconcile_interrupted_runs`): under ARQ a `running` run is being **retried**, not lost, so reconcile MUST NOT prematurely mark it failed while a live/queued ARQ job exists for it — gate reconcile on "no live ARQ job" or rely on run-status idempotency so a retried job supersedes a reconciled row (G3). Add a regression test for the reconcile-vs-retry interaction

**Checkpoint**: US1 independently testable — pipeline is durable end-to-end via manual triggers; MVP done.

---

## Phase 4: User Story 2 — Watchlists run their full cycle on cadence (Priority: P2)

**Goal**: Hourly scheduler runs the complete cycle (ingest→index→triage→expedited→consolidate) for due
watchlists; watchlist-scoped index; cycle-state machine; budget policy; suspended-client exclusion;
catch-up coalescing.

**Independent test**: seed varied cadence/last-cycle/clock → tick selects exactly due watchlists; a due
watchlist advances to a consolidated report; not-due/inactive/suspended skipped; overdue → one cycle.

- [X] T025 [P] [US2] `tests/unit/test_due_selection.py` — cadence interval math, coalescing, suspended/inactive exclusion (the golden-set logic)
- [X] T026 [P] [US2] `eval/scheduling/run_due_selection_eval.py` — score fixtures → `precision=1.0, recall=1.0` against `eval_thresholds.yaml`
- [X] T027 [P] [US2] `tests/unit/test_budget_policy.py` — `continue`/`critical_only`/`pause` gate + Constitution III invariant (serious findings never suppressed)
- [X] T028 [US2] Watchlist-scope the index step (D7): add `watchlist_id` param to `IndexBuildService.create_run` + `get_documents_to_index` (`app/embedding/service.py`) and `index_build_runner` (`app/embedding/runner.py`); filter `DocumentWatchlist`; preserve client-wide manual path (watchlist_id NULL)
- [X] T029 [P] [US2] Implement due-ness logic in `app/scheduling/due.py` (UTC cadence intervals: daily=1d, weekly=7d, biweekly=14d, **monthly = add one calendar month** not fixed 30d; coalescing; pure + unit-testable)
- [X] T030 [US2] Implement cycle-state service in `app/scheduling/service.py`: `start_cycle`, `advance_stage`, `mark_failed`, `mark_completed`, `abandon_cycle` (sets `resolved_at`); due-watchlist query = active client + active non-empty watchlist + no in-progress cycle + **no unresolved `failed` cycle** (FR-018a — see data-model due-ness ⚠️); in-progress partial-unique guard
- [X] T031 [US2] Implement budget gate in `app/scheduling/budget_policy.py` using `derive_budget_state`/`read_figures` (reuse, don't recompute); dispatch `WatchlistBudgetThresholdReached` on warning/exceeded transitions (FR-019c)
- [X] T032 [US2] Implement `scheduler_tick` in `app/jobs/scheduler.py` and register `cron(scheduler_tick, minute=settings.scheduler_tick_cron_minute)` in `worker/worker.py` cron_jobs
- [X] T033 [US2] Add `task_cycle_start` + `task_consolidate` to `app/jobs/tasks.py` and wire chain advancement (each stage enqueues next; failure → cycle `failed`+`failure_stage`; consolidation honors budget gate then marks `completed`)
- [X] T033a [US2] Convert the **manual** `consolidate-batch` endpoint (`app/reports/routes.py:259`, currently inline `await consolidate_batch`) → `enqueue("task_consolidate", job_id="consolidate:manual:{watchlist_id}:{period_start_iso}", ...)` returning **202** (FR-001/G1). ⚠️ API contract change (sync report → 202): verify/adjust the spec-10 admin-console consolidate trigger (record in forward-dependency ledger)
- [X] T034 [US2] Add `budget_exceeded_policy` to the watchlist update path in `app/clients/routes_watchlists.py` + request/read schemas (`app/clients/schemas.py`); emit existing watchlist-config event
- [X] T035 [P] [US2] Add cycle endpoints: `GET /clients/{id}/watchlists/{wid}/cycles` (read) + `POST /clients/{id}/watchlists/{wid}/cycles/{cycle_id}/abandon` (resolve a `failed` cycle → sets `resolved_at`, FR-018b) + schemas
- [X] T036 [US2] End-to-end cycle integration test in `tests/integration/test_scheduling_reliability.py` (or a sibling): full chain advancement, catch-up coalescing (FR-015b), suspended-client exclusion (FR-013), overlap prevention (FR-017), **failed-cycle is NOT auto-rescheduled until abandoned/resolved (FR-018a/018b)**, and **HITL invariant: an automated cycle never sets a report to approved/sent (FR-024)**

**Checkpoint**: US2 independently testable — automation runs cycles on cadence with budget + safety rules.

---

## Phase 5: User Story 3 — Operator visibility for dead-lettered jobs (Priority: P3)

**Goal**: Operators see and act on failed jobs via dashboard + audit; retention purge.

**Independent test**: force a job to exhaust retries → `dead_letter` row + `JobDeadLettered` audit row +
`GET /admin/dead-letters` shows it; resolve clears it; purge removes expired without touching audit.

- [X] T037 [P] [US3] Implement `GET /admin/dead-letters` (filter `resolved=false`, `client_id`) + `POST /admin/dead-letters/{id}/resolve` (staff-only) + schemas (no payloads/PII in responses)
- [X] T038 [US3] Surface dead-letter count/list on the spec-10 admin dashboard (backend metric in the existing dashboard endpoint; light up the failed-jobs card)
- [X] T039 [P] [US3] Implement `purge_expired` in `app/jobs/dead_letter.py` + register daily `cron(purge_dead_letters,...)`; purge MUST NOT delete audit rows (FR-009a)
- [X] T040 [US3] Integration test: dead-letter → audit-row assertion + endpoint surfacing + retention purge

**Checkpoint**: US3 independently testable — failures are operator-visible and audited.

---

## Phase 6: Polish & Cross-Cutting

- [X] T041 [P] Add scheduling gates to CI `eval` job in `.github/workflows/ci.yml`: due-selection eval (pure-Python) + reliability suite (place reliability in the DB-backed `test` job if `eval` lacks Postgres — see implementation-notes §9)
- [X] T042 [P] Add the ARQ worker service/command (`arq worker.worker.WorkerSettings`) to `docker-compose.yml` (and override if needed)
- [X] T043 [P] Structured logging for the full job lifecycle (enqueued/started/completed/retried/dead-lettered) binding client/run/finding ids, no PII (FR-020)
- [X] T044 Run full gate: `uv run ruff check app worker tests` + `uv run black --check app worker tests` + unit + integration green; fix drift
- [X] T045 [P] Runbook note (docs/) for running the worker + scheduler; update the frontend forward-dependency ledger "Resolved" once budget-policy endpoint + dead-letter card backend ship

---

## Dependencies & Execution Order

- **Setup (P1.T001–T003)** → **Foundational (T004–T011)** block everything.
- **US1 (T012–T024)** depends only on Foundational → **MVP**; independently shippable.
- **US2 (T025–T036)** depends on Foundational + US1's `enqueue`/tasks/worker registration (T014, T016, T017).
- **US3 (T037–T040)** depends on Foundational + US1's dead-letter recording (T015).
- **Polish (T041–T045)** last.
- US2 and US3 are independent of each other (both build on US1) and may proceed in parallel once US1 lands.

## Parallel Execution Examples

- **Setup**: T002, T003 in parallel (T001 separate file but independent).
- **Foundational**: T005, T006, T007, T008, T010 in parallel (distinct files) after T004 (migration) is drafted; T009/T011 touch worker/lifespan.
- **US1 call-site conversions**: T018–T021 in parallel (different route files) after T014/T016; T022 after (shares the index/triage path).
- **US2 tests**: T025, T026, T027 in parallel before/alongside implementation.
- **US3**: T037, T039 in parallel.

## Implementation Strategy

- **MVP = Phase 1 + 2 + US1.** Delivers durable, idempotent, retried, dead-letter-recorded pipeline with
  inline parity — the core reliability win — even before cron automation exists.
- **Increment 2 = US2** turns on the hands-off cadence loop (the headline operator value).
- **Increment 3 = US3** adds operator visibility/retention.
- Keep each `app/jobs/*` and `app/scheduling/*` file focused (≤~300 lines). Verify against
  implementation-notes before each task; run BOTH linters before every commit.
