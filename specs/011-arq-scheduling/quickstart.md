# Quickstart & Validation: ARQ Scheduling

Run/validate the durable pipeline + scheduler. Details live in `contracts/` and `data-model.md`; this is a
run guide, not implementation.

## Prerequisites

- Compose stack up (Postgres 5433, Redis 6380, Vault 8200) per `memory/dev-environment.md`.
- Secrets in Vault (`scripts/write_secrets.py`); `redis_url` present (the ARQ broker).
- Migrations applied: `uv run alembic upgrade head` (must include `0010_scheduling`).

## Run the worker (durable mode)

```powershell
# API as usual (uvicorn). Separately, the ARQ worker:
uv run arq worker.worker.WorkerSettings
```

Expect `worker.startup.complete`; the hourly `scheduler_tick` and daily `purge_dead_letters` cron jobs are
registered. The worker shares the API image/entrypoint differs only by command.

## Run jobs inline (dev/tests, no worker)

Set `JOBS_INLINE=1` (maps to `Settings.jobs_inline`). Triggers execute in-process — same functions, same
persisted results (parity). Never set this in production; a startup assertion forbids it there.

## Validation scenarios (map to Success Criteria)

1. **Durable survival (SC-001).** Trigger ingestion; kill the worker mid-run; restart → run completes once;
   no duplicate documents. (Integration: simulate via re-enqueue of the same `ingest:{run_id}`.)
2. **Idempotency (SC-002).** Enqueue the same job id twice → underlying work runs once (assert row counts).
3. **Retry then succeed (SC-003).** Inject a transient error (fail twice, succeed third) → completes with
   no operator action; assert `transient_retry_recovery = 1.0`.
4. **Permanent no-retry (SC-003).** Raise `PermanentJobError` → 1 attempt, straight to dead-letter.
5. **Dead-letter (SC-004).** Exhaust retries → `dead_letter` row + `JobDeadLettered` audit row +
   `GET /admin/dead-letters` shows it.
6. **Graceful drain (SC-005).** SIGTERM with an in-flight job → finishes or is left re-runnable; never
   marked falsely complete.
7. **Due-selection (SC-006).** Seed watchlists with varied cadence/last-cycle/clock; run `scheduler_tick`
   → exactly the due set starts a cycle; no overlap. (Eval: `eval/scheduling/run_due_selection_eval.py`
   → precision/recall = 1.0.)
8. **End-to-end cycle (SC-007).** A due watchlist advances ingestion→index→triage→expedited→consolidation
   to `completed` with no manual action.
9. **Parity (SC-008).** Same inputs under `jobs_inline=true` vs durable → identical persisted state.
10. **Catch-up (FR-015b).** Watchlist overdue by N intervals → exactly one cycle on recovery.
11. **Suspended client (FR-013).** Suspend a client → its watchlists are skipped by `scheduler_tick`.
12. **Budget policy (SC-012).** Over-budget watchlist with `pause`/`critical_only` → drafting skipped per
    policy, but a seeded urgent/emergency finding still gets detection/escalation/expedited handling.

## Gate commands (CI `eval` job)

```powershell
uv run pytest tests/integration/test_scheduling_reliability.py -v   # reliability invariants
PYTHONPATH=. uv run python eval/scheduling/run_due_selection_eval.py # due-selection precision/recall=1.0
uv run pytest tests/unit/test_due_selection.py tests/unit/test_budget_policy.py -v
```

## Lint (both must pass)

```powershell
uv run ruff check app worker tests ; uv run black --check app worker tests
```
