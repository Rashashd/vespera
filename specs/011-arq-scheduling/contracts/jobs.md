# Contract: ARQ Job Catalog

Each job is an `async def task_*(ctx, ...)` in `app/jobs/tasks.py`, registered in
`worker.worker.WorkerSettings.functions`. `ctx` carries the `WorkerContext` (D2). Every task wraps an
**existing** stage runner; it adds only: deterministic job-id idempotency (D3), transient/permanent
classification (D4), dead-letter on exhaustion (D5), and (for chain stages) enqueue-of-next on success.

`enqueue(name, *, job_id, queue_args)` (`app/jobs/enqueue.py`) is the single entry point used by routes
**and** by the scheduler/chain. It enqueues to ARQ, or — when `Settings.jobs_inline` is True — awaits the
task coroutine in-process with the same args (parity, D8). Broker-down surfaces an error (FR-002a).

| Job (ARQ name) | Wraps | Deterministic `job_id` | Retry class on failure | On success enqueues |
|---|---|---|---|---|
| `task_run_ingestion` | `ingestion.runner.run_ingestion` | `ingest:{run_id}` | transient | `task_index_build` (cycle path) |
| `task_index_build` | `embedding.runner.index_build_runner` (+`watchlist_id`) | **cycle:** `index:{client_id}:{watchlist_id}:{cycle_id}` · **manual (client-wide, `watchlist_id=NULL`):** `index:{client_id}:manual:{run_id}` | transient | triage fires inline by the indexer → keep (see notes §2) |
| `task_triage` *(OPTIONAL — triage runs INLINE within `task_index_build` by default; build this only if splitting triage into a standalone per-doc stage, see implementation-notes §2)* | `triage.runner.triage_document_runner` | `triage:{document_id}` | transient | `task_expedited` per urgent/emergency finding |
| `task_expedited` | `reports.runner.draft_expedited` | `expedited:{finding_id}:{revision}` (auto fan-out / first draft = revision **0**; a finding has no `revision` field) | transient | — (independent, no join — FR-015a) |
| `task_redraft` | `reports.runner.redraft_report` | `redraft:{report_id}:{revision}` | transient | — |
| `task_consolidate` | `reports.consolidation.consolidate_batch` | `consolidate:{cycle_id}` | transient | marks cycle `completed` |
| `task_cycle_start` | `scheduling.service.start_cycle` | `cycle-start:{watchlist_id}:{period_start_iso}` | permanent-on-validation | `task_run_ingestion` |
| `task_purge_dead_letters` | `jobs.dead_letter.purge_expired` | n/a (cron) | transient | — |

**Idempotency contract.** ARQ rejects a duplicate `_job_id` already queued/running; additionally each
runner is a no-op if its DB row is already past the relevant status (ingestion/index run status; report
status; cycle `current_stage`). Re-enqueue or retry MUST NOT double-write (FR-005, SC-002).

**Failure contract.** Tasks raise `PermanentJobError` (`app/jobs/retry.py`) for 4xx/validation/business-rule
errors → straight to dead-letter, no retry (FR-008). Any other exception is transient → ARQ retries up to
`max_tries=3` with backoff (FR-007). On the final failed try, `jobs.dead_letter.record(...)` inserts the
`dead_letter` row and dispatches `JobDeadLettered` (system actor → audit). A cycle whose chain stage
dead-letters is marked `failed` with `failure_stage` (FR-018) and excluded from auto-scheduling (FR-018a).

**Budget gate (chain only).** Before `task_expedited`/`task_consolidate` an automated cycle consults
`scheduling.budget_policy.gate(...)`: `continue` → run; `critical_only` → run expedited, skip
consolidation (set `skipped_reason`); `pause` → skip both. Detection/escalation/alerting already happened
upstream in triage and are never skipped (Constitution III, FR-019b, SC-012). Manual triggers bypass the
gate.

**Concurrency.** `WorkerSettings.max_jobs = Settings.worker_max_jobs` bounds expedited fan-out (FR-015c).
`job_timeout = Settings.worker_job_timeout`; shutdown grace defaults to that timeout (FR-012).
