# Contract: Cron Scheduler & Cycle Chain

## Cron registration

`worker.worker.WorkerSettings.cron_jobs` gains:
- `scheduler_tick` — runs hourly (`arq.cron(scheduler_tick, minute=0)`), `run_at_startup=False`.
- `purge_dead_letters` — runs daily (e.g. `arq.cron(..., hour=3, minute=0)`), retention purge (FR-009a).

ARQ runs a given cron job once across the worker pool (timestamped internal job id), so multiple replicas
do not double-fire the tick. Cycle creation is additionally idempotent (below), so even a double-fire is safe.

## `scheduler_tick(ctx)` — due-selection (FR-013)

1. Open a session via the worker context.
2. Select **due** watchlists with one query (see `data-model.md` §Due-ness): client `status='active'`,
   watchlist `is_active=true` and has ≥1 item, **no** `in_progress` cycle, **no unresolved `failed` cycle**
   (`status='failed' AND resolved_at IS NULL` → excluded, FR-018a), and
   (`no completed cycle` OR `now_utc - last_completed_at ≥ interval(cadence)`).
   `interval`: daily=1d, weekly=7d, biweekly=14d, **monthly = add one calendar month** (not 30d), UTC.
3. For each due watchlist, `enqueue("task_cycle_start", job_id="cycle-start:{wl}:{period_start_iso}",
   ...)`. The deterministic id + the partial-unique `in_progress` guard mean an overdue-by-N watchlist
   starts exactly **one** cycle (coalescing, FR-015b).
4. Log `scheduler.tick {due_count}`; never raise for a single bad watchlist (isolate, continue).

`period_start` = the last completed cycle's `completed_at` (or watchlist creation for first run);
`period_end` = tick time. These feed `consolidate_batch(cycle_period_start, cycle_period_end)`.

## `start_cycle(...)` (task_cycle_start)

Creates the `watchlist_cycles` row (`status='in_progress'`, `current_stage='ingestion'`,
`cadence_at_start`, `period_*`), creates the ingestion run row, then enqueues `task_run_ingestion`. If a
validation precondition fails (watchlist vanished/deactivated/client suspended between tick and start),
raise `PermanentJobError` → recorded, no retry, no cycle.

## Chain advancement (FR-014/FR-015)

```
task_cycle_start → task_run_ingestion → task_index_build(watchlist_id) → (indexer fires triage per doc)
   → task_triage → [urgent/emergency] task_expedited (fan-out, independent)
   → [cycle end] task_consolidate → cycle.status=completed, current_stage=done, completed_at=now
```

- Each stage updates `watchlist_cycles.current_stage` before handing off.
- Stage success enqueues the next stage with the cycle id in the job key.
- Stage dead-letter → `cycle.status='failed'`, `failure_stage=<stage>`, `completed_at=now` (terminal for
  auto-scheduling; FR-018/FR-018a). No next stage is enqueued.
- Expedited drafts are fanned out but **not** awaited by consolidation (FR-015a); a failed expedited draft
  dead-letters on its own and does not change cycle completion.
- Consolidation honours the budget gate (`critical_only`/`pause` may skip it, setting `skipped_reason`)
  but the cycle still reaches a terminal `completed` state so the next due time advances.

## Manual triggers (FR-019)

Existing endpoints (ingest / index-build / reject→redraft / consolidate-batch) keep working: they call the
same `enqueue(...)` with their own job ids, subject to the same idempotency + single-in-flight guards, and
are **not** budget-gated (operator override). They do not create a `watchlist_cycles` row unless explicitly
starting a cycle.
