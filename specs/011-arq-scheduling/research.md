# Research: Durable ARQ Job Orchestration & Cron Scheduling

All decisions below are grounded in the live codebase (anchors in
[implementation-notes.md](./implementation-notes.md)) and the resolved spec clarifications. No open
`NEEDS CLARIFICATION` remain.

## D1 — Durable execution engine: ARQ (no new dependency)

**Decision.** Use ARQ over Redis as the durable queue. `arq>=0.26` is already in `pyproject.toml` and
`worker/worker.py` is a working skeleton (shared Vault/engine/redis bootstrap, `RedisSettings`,
`heartbeat` placeholder, empty `cron_jobs`).

**Rationale.** Constitution VI names the ARQ worker as the platform execution model; the broker (Redis)
already exists. No new broker, no MCP.

**Alternatives considered.** Celery (heavier, sync-first), custom asyncio loop (reinvents retry/cron),
keeping `BackgroundTasks` (the very problem — lost on restart). Rejected.

## D2 — Stage runners are wrapped, not rewritten

**Decision.** Add a thin `app/jobs/tasks.py` whose ARQ functions call the existing runners unchanged:
`run_ingestion(**kwargs)`, `index_build_runner(...)`, `triage_document_runner(...)`,
`draft_expedited(finding_id, app_state)`, `redraft_report(report_id=, comment=, app_state=)`,
`consolidate_batch(watchlist_id=, client_id=, cycle_period_start=, cycle_period_end=, session=, dispatcher=)`.

**Rationale.** Runners were intentionally written framework-agnostic (`run_ingestion` docstring:
"callable from spec-11 ARQ without modification"). Minimises blast radius.

**Consequence — worker context shim.** Runners expect either a `session_factory` callable or an
`app_state` object exposing `settings/session_factory/redis/dispatcher`. The worker has no FastAPI
`request.app.state`, so `app/jobs/context.py` builds a `WorkerContext` from the ARQ `ctx` (set up in
`on_startup`) exposing those attributes. **The worker MUST build a dispatcher and call
`register_audit_handlers(dispatcher)`** — it does not today, so worker-run jobs would otherwise emit no
audit rows. See implementation-notes §Worker.

## D3 — Idempotency via deterministic ARQ job IDs + DB-state guards

**Decision.** Compute a deterministic `_job_id` per logical work key and pass it to `enqueue_job(_job_id=...)`.
ARQ refuses to enqueue a job whose ID is already queued/in-progress, collapsing duplicate enqueues. On top
of that, each runner already guards on DB state (ingestion/index run status; report status;
finding/cycle status), so a re-run is a no-op.

Keys: `ingest:{run_id}`, `index:{client_id}:{watchlist_id}:{cycle_id}`, `triage:{document_id}`,
`expedited:{finding_id}:{revision}`, `redraft:{report_id}:{revision}`, `consolidate:{cycle_id}`,
`cycle-start:{watchlist_id}:{period_start_iso}`.

**Rationale.** Two-layer defence (queue-level + state-level) satisfies FR-005 even under retries and
overlapping scheduler ticks.

**Alternatives.** DB advisory locks only (does not stop duplicate enqueue); ARQ `job_id` only (does not
cover a job re-queued after completion+expiry) — combined approach chosen.

## D4 — Retry: 3 job-level tries on top of in-call tenacity; permanent errors don't retry

**Decision.** Set `max_tries=3` (ARQ retries via `Retry`/raised exception) with exponential backoff.
`app/jobs/retry.py` defines `PermanentJobError`; tasks raise it for 4xx-class/validation/business-rule
failures, which are caught and routed straight to dead-letter (no retry). Transient errors (timeout, 5xx,
connection, process death) exhaust the 3 tries. The existing per-call `tenacity` `stop_after_attempt(3)`
(no-retry-on-4xx) stays underneath each external call.

**Rationale.** FR-007/FR-008. Mirrors the constitution's external-call retry contract at the job layer.

## D5 — Dead-letter: table + system-actor audit event + dashboard card

**Decision.** A `dead_letter` table (migration 0010) records exhausted jobs. On final failure
`app/jobs/dead_letter.py` inserts the row and dispatches a new `JobDeadLettered(actor_id=0,
actor_type="system", client_id=…, job_name, job_key, attempts, error_class)` domain event. The existing
`register_audit_handlers` auto-discovers `DomainEvent` subclasses, so the event flows to the append-only
`audit_log` with no human FK (the `actor_id=0` sentinel convention already used by triage/consolidation).
A read endpoint + a spec-10 admin dashboard card surface current dead-letters.

**Rationale.** FR-009/FR-010/FR-021; answers the owner's "add it to audit log?" cleanly without polluting
human-action semantics. Retention default 90 days, configurable (FR-009a); purge never deletes audit rows.

**Alternatives.** Audit-only (no queryable store; weak ops) and logs-only (no durability) — rejected.

## D6 — Full cadence loop via hourly cron + chain-by-completion

**Decision.** Register an ARQ `cron_job` on an hourly tick (`app/jobs/scheduler.py:scheduler_tick`). It
selects **due** watchlists — client `active`, watchlist `is_active`, has items, and
`now - last_completed_cycle ≥ cadence_interval` (UTC) — and starts one cycle each via a deterministic
`cycle-start` job. Each stage task, on success, enqueues the next stage (`ingest → index → triage →
expedited fan-out + consolidate`), advancing the `watchlist_cycles` row's `current_stage`.

**Rationale.** FR-013/FR-014/FR-015. Hourly comfortably serves daily-or-coarser cadence; chain-by-
completion avoids one giant long-running task and lets each stage retry/dead-letter independently.

**Catch-up (FR-015b).** Overdue-by-many-intervals → exactly one coalesced cycle; ingestion watermarks
(`source_watermarks`) already cover the accumulated backlog. Next due computed from completion.

**Topology.** ARQ coordinates a cron job to run once across a worker pool (timestamped job id), and cycle
creation is idempotent (`cycle-start` key), so multiple replicas are safe. Singleton-vs-replica is left to
deployment (plan-level, recorded in spec §Deferred to Planning).

## D7 — Watchlist-scoped index step (touches spec-6 schema, deliberately)

**Decision.** Per the second-pass clarification (Option B), the cycle's index step indexes only the
triggering watchlist's documents. Migration 0010 adds `index_build_runs.watchlist_id` (nullable — NULL =
the existing client-wide manual rebuild), swaps the partial-unique guard
`uq_index_build_runs_client_running (client_id) WHERE status='running'` → a per-(client, watchlist)
variant, and `IndexBuildService.create_run` / `get_documents_to_index` / `index_build_runner` gain a
`watchlist_id` parameter that filters `DocumentWatchlist`.

**Rationale.** Clean, auditable per-cycle provenance in a regulated domain; the client-wide manual rebuild
is preserved (watchlist_id NULL). Implementation-notes pins the exact constraint migration + full caller
list (the de-risk for the cold implementer).

**Alternatives.** Per-client shared index (Option A — fuzzy provenance) and per-client cycles (Option C —
conflicts with per-watchlist cadence). Rejected by owner.

## D8 — Durable-in-prod, inline-for-tests (`jobs_inline`)

**Decision.** Add `Settings.jobs_inline: bool = False`. `app/jobs/enqueue.py:enqueue()` branches: prod
enqueues to ARQ; when `jobs_inline` is True it `await`s the task coroutine in-process (same function, same
persisted result). Production config never sets it True; a startup assertion forbids
`jobs_inline and not <dev marker>` so it is "provably unavailable in production" (SC-008).

**Rationale.** FR-003/FR-004. Keeps the existing integration suite runnable without a live worker and
gives behavioral parity as a committed metric.

**Broker-down at enqueue (FR-002a).** `enqueue()` surfaces a broker connection failure to the caller (the
human request errors; the scheduler tick logs + relies on the next tick); never silent-drop, never silent
inline fallback in prod.

## D9 — Budget-aware automation (no auto-stop default)

**Decision.** Add `watchlists.budget_exceeded_policy` (`continue` default / `critical_only` / `pause`),
settable via an admin endpoint. `app/scheduling/budget_policy.py` reads the existing
`derive_budget_state` (`app/clients/_helpers.py`) for the current UTC month and gates only the LLM
drafting steps of an automated cycle; serious-finding detection/severity/escalation/operator-alert always
run (Constitution III). Budget `warning`/`exceeded` transitions dispatch a domain event (dashboard +
audit); active email send is spec 13.

**Rationale.** Owner decision — removing the human spend-gate must not silently halt the service, but must
respect a configurable cap while never cost-suppressing a serious AE. FR-019a–d, SC-012.

## D10 — Merge gate: reliability + due-selection eval, committed to `eval_thresholds.yaml`

**Decision.** Add a `scheduling` block to `eval_thresholds.yaml` and CI `eval` steps:
- due-selection golden set → `precision = 1.0`, `recall = 1.0` (`eval/scheduling/run_due_selection_eval.py`);
- reliability invariants asserted by `tests/integration/test_scheduling_reliability.py`:
  `duplicate_rate = 0`, `loss_rate = 0`, `transient_retry_recovery = 1.0`, `inline_vs_durable_parity = 1.0`.

**Rationale.** Constitution IV — an infra spec still ships a number. The due-selection set is the genuinely
model-like surface; the invariants are binary correctness gates. Mirrors the existing CI `eval` job shape
(triage/agent/grounding gates run as pytest steps).
