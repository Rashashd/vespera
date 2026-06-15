# Implementation Notes — READ FIRST (anti-hallucination guide)

**Spec 11 `011-arq-scheduling`.** A weaker model implements this cold. Every anchor below was verified
against live code on branch `011-arq-scheduling` (base `master` @ `142dcb5`). VERIFY again with grep if in
doubt — do NOT invent signatures. Things that **do not exist yet** are flagged `❌ DOES NOT EXIST`.

---

## 0. The five trigger sites to make durable (this is the heart of the spec)

Replace each with `app/jobs/enqueue.py:enqueue(...)`. **Site 5 is the easy-to-miss one.**

| # | File:line | Today | Wrap as |
|---|---|---|---|
| 1 | `app/ingestion/routes_ingestion.py:84` | `background_tasks.add_task(run_ingestion, ...)` | `task_run_ingestion` |
| 2 | `app/embedding/routes.py:67` | `background_tasks.add_task(_run_index_build_background, ...)` | `task_index_build` |
| 3 | `app/reports/routes.py:166` | `background_tasks.add_task(redraft_report, ...)` | `task_redraft` |
| 4 | `app/reports/routes.py:343` | `background_tasks.add_task(draft_expedited, finding_id, request.app.state)` | `task_expedited` (manual) |
| 5 | `app/embedding/triage_trigger.py:85` | **`asyncio.create_task(draft_expedited(outcome.finding_id, app_state))`** | `task_expedited` (auto fan-out) |

⚠️ **Site 5** is the automatic post-triage expedited trigger (`triage_trigger.py:73-85`, guarded by
`outcome.bucket in (Bucket.URGENT, Bucket.EMERGENCY)`). It is a **fire-and-forget `asyncio.create_task`** —
lost on restart, unawaited, no retry. Converting it to a durable `enqueue("task_expedited",
job_id=f"expedited:{finding_id}:{revision}")` is the single most important reliability fix in the chain.

---

## 1. Stage runner signatures (wrap, do NOT rewrite)

- `app/ingestion/runner.py:38`
  `async def run_ingestion(*, run_id, client_id, watchlist_id, watchlist_items: list, session_factory: Callable, initial_lookback_days=365, per_source_cap=200, adapters=None) -> None`
  — already framework-agnostic ("callable from spec-11 ARQ without modification"). `watchlist_items` is a
  list of ORM rows snapshotted by the route; the job must re-load them in the worker (see §3 caveat).
- `app/embedding/runner.py:25`
  `async def index_build_runner(session_factory, client_id, modelserver_client=None, triggered_by_user_id=None, dispatcher=None, app_state=None) -> IndexBuildRun`
  — **add a `watchlist_id` parameter** (D7). It calls `IndexBuildService.create_run` and
  `get_documents_to_index` (both need the new `watchlist_id`).
- `app/embedding/routes.py` `_run_index_build_background(...)` is a thin wrapper around the runner — the
  job can call `index_build_runner` directly with a `WorkerContext`.
- `app/triage/runner.py:19` `triage_document_runner(...)` — **runs INLINE today** inside the index build
  per-doc loop (`document_indexer.py:229` → `triage_trigger.py:61`). See §2.
- `app/reports/runner.py:14` `async def draft_expedited(finding_id: int, app_state) -> None`
- `app/reports/runner.py:99` `async def redraft_report(*, report_id: int, comment: str, app_state) -> None`
- `app/reports/consolidation.py:26`
  `async def consolidate_batch(*, watchlist_id, client_id, cycle_period_start, cycle_period_end, session, dispatcher) -> Report | None`
  — note this takes a **live `session`** (not a factory); the consolidate job opens the session and passes it.

`draft_expedited`/`redraft_report` read `app_state.{settings,session_factory,redis,dispatcher}` — so the
worker MUST provide an `app_state`-shaped object (the `WorkerContext`, §3).

---

## 2. Triage is INLINE within index build — recommended chain mapping

`index_build_runner` → `document_indexer.py:229` calls `trigger_triage(...)` per freshly-indexed doc →
`triage_trigger.py:61` runs `triage_document_runner` → `:85` fires expedited. Per-doc errors are already
isolated inside the indexer.

**RECOMMENDED (low blast radius):** keep triage inline inside `task_index_build` (the "index" stage =
index + triage). Make only the **expedited** fan-out durable (site 5). Triage is idempotent per doc via
`DocumentIndexState`, so an index-job retry re-triages safely.

**Therefore `task_triage` in `contracts/jobs.md` is OPTIONAL** — only build it if you choose to split
triage into a standalone enqueued per-doc stage. The default plan does NOT require it; do not refactor
`document_indexer` unless you take that option. Either way, FR-015's "advance by job completion" is honored
at the ingestion→index→(expedited fan-out)→consolidate boundaries.

---

## 3. Worker context — the biggest gotcha

`worker/worker.py` TODAY (verified lines 15-32) builds in `startup(ctx)`: `settings`, `engine`, `redis`,
`llm`. It does **NOT** build `session_factory` or `dispatcher`, and does **NOT** call
`register_audit_handlers`. Jobs run in the worker would therefore (a) have no `session_factory`/`dispatcher`
and (b) **emit no audit rows**.

Copy the construction from `app/core/lifespan.py:62-81`:
```
dispatcher = EventDispatcher()                       # app/core/dispatcher.py
register_audit_handlers(dispatcher)                  # app/audit/handler.py:52
session_factory = create_session_factory(engine)     # app/db/base.py:23
```
Add `session_factory` + `dispatcher` to `ctx` in `on_startup`. `app/jobs/context.py:WorkerContext` exposes
`.settings .session_factory .redis .dispatcher .llm` (duck-types `app.state`) so `draft_expedited` /
`redraft_report` work unchanged.

⚠️ `run_ingestion` receives `watchlist_items` as ORM rows. In a job you only have ids — **re-query** the
watchlist + items in the worker session before calling `run_ingestion` (mirror
`routes_ingestion.py:46-80` which loads `watchlist.items` then snapshots). Pass the freshly-loaded list.

---

## 4. ARQ specifics (verified: `arq>=0.26` in `pyproject.toml:13`; `worker/worker.py` skeleton)

- **Enqueue:** `redis = await create_pool(RedisSettings...)` then `await redis.enqueue_job("task_name",
  ..., _job_id="...")`. A duplicate `_job_id` already queued/running returns `None` (idempotency, D3). The
  API already has a Redis client (`app.state.redis`); reuse an ARQ pool or the same Redis — confirm ARQ
  needs `create_pool` (an `ArqRedis`), distinct from the app's `redis` client. Build the ARQ pool once on
  app startup and stash on `app.state` (e.g. `app.state.arq`).
- **`enqueue()` must work in BOTH contexts (G5):** from the API it uses `app.state.arq`; from **inside a
  running worker job** (site 5 enqueues `task_expedited` from within `task_index_build`'s triage loop) it
  must use the worker's ARQ connection — in ARQ, `ctx['redis']` IS an `ArqRedis` with `enqueue_job`. Make
  `enqueue()` accept/resolve the connection so it works on both sides; the `WorkerContext` should expose it.
- **Retry:** set `max_tries=3` on the function (or `WorkerSettings`); raise to retry, raise
  `PermanentJobError` (❌ create in `app/jobs/retry.py`) to NOT retry — catch it in the task and dead-letter
  directly. ARQ also exposes `ctx['job_try']` for attempt count.
- **Cron:** `from arq import cron`; `cron_jobs = [cron(scheduler_tick, minute=0), cron(purge_dead_letters,
  hour=3, minute=0)]`. ARQ runs a cron once across the pool.
- **Broker TLS (FR-023):** TODAY `worker.py:48` hardcodes `RedisSettings(host="redis", port=6379)`.
  CHANGE to derive from `settings.redis_url` via `RedisSettings.from_dsn(settings.redis_url)` so `rediss://`
  works in prod. Do the same for the enqueue pool.
- **Graceful shutdown (FR-012):** `handle_signals=True` is already set; ARQ drains on SIGTERM. Set the
  grace via `WorkerSettings` job timeout; expose `Settings.worker_shutdown_grace_seconds` (default = job
  timeout).

---

## 5. Settings additions — `app/core/config.py` (extra="forbid"; defaults only, NO secrets)

Add to `Settings` (around the spec-9/10 block, lines 72-85). Env override is automatic (e.g.
`JOBS_INLINE=1`). `extra="forbid"` means every new env key MUST have a field here.
```
jobs_inline: bool = False                       # dev/test only; prod assertion forbids True
worker_max_jobs: int = 10                        # bounds expedited fan-out (FR-015c)
worker_job_timeout: int = 600                    # per-job seconds (index/draft can be slow)
worker_shutdown_grace_seconds: int = 600         # default = job timeout (FR-012)
scheduler_tick_cron_minute: int = 0              # hourly tick
dead_letter_retention_days: int = 90             # FR-009a
```
Add a startup assertion (in lifespan, after secrets) that `jobs_inline` is False unless an explicit dev
marker is set, so it is "provably unavailable in production" (SC-008). There is NO existing `os.getenv`
outside config — keep it that way.

---

## 6. Migration 0010 — `app/db/migrations/versions/0010_scheduling.py`

- **`down_revision = "0009"`** (head verified = `0009_llm_usage.py`). `revision = "0010"`.
- New tables `watchlist_cycles`, `dead_letter`; alter `index_build_runs` (+`watchlist_id`, swap
  partial-unique), alter `watchlists` (+`budget_exceeded_policy`). Full column list in `data-model.md`.
- **Partial-unique pattern** to copy verbatim (from `0006_chunks_index_state.py:127-133`):
  `op.create_index("uq_...", "table", ["col"], unique=True, postgresql_where="status = 'running'")`.
- **Index-run guard swap:** drop `uq_index_build_runs_client_running`, create
  `uq_index_build_runs_client_wl_running` on `["client_id","watchlist_id"]` `WHERE status='running'`.
  ⚠️ NULL `watchlist_id` rows are distinct under a unique index — the client-wide manual build keeps its
  own self-guard in `IndexBuildService.create_run` (`app/embedding/service.py:18-40`, select-existing). Do
  NOT rely on the unique index alone for the manual path.
- Provide a real `downgrade()` (drop in reverse; restore the old `(client_id) WHERE running` index). Follow
  the in-place migration discipline: `downgrade → edit → upgrade` when iterating on a feature branch.
- CHECK constraints: cycle `status`/`current_stage`, `budget_exceeded_policy` (see data-model). Mirror the
  `_CADENCE_NEW` CHECK style in `0008_reports_and_followups.py:25`.

---

## 7. Domain events — `app/domain/events.py`

Base `DomainEvent(actor_id, actor_type, client_id=None)` (`events.py:6-12`). **System events use
`actor_id=0, actor_type="system"`** (verified `reports/consolidation.py:138-154`, `triage/service.py:171`).
`register_audit_handlers` (`audit/handler.py:52`) auto-walks `DomainEvent.__subclasses__()`, so a new
frozen dataclass subclass is audited automatically — **but the module defining it must be imported before
`register_audit_handlers` runs** (it already imports `app.domain.events`; keep new events there).

Add:
```
@dataclass(frozen=True, slots=True)
class JobDeadLettered(DomainEvent):
    job_name: str = ""; job_key: str = ""; attempts: int = 0; error_class: str = ""

@dataclass(frozen=True, slots=True)
class WatchlistBudgetThresholdReached(DomainEvent):
    watchlist_id: int = 0; state: str = ""   # "warning" | "exceeded"
```
`audit/handler.py:_target_for` (lines 12-28) maps known id attrs to a target; `watchlist_id` is already
handled, `JobDeadLettered` falls through to the class name (fine) — optionally add a `job_key` branch.

---

## 8. Budget — reuse, don't reinvent

`app/clients/_helpers.py:42 derive_budget_state(budget, spend) -> "ok"|"warning"|"exceeded"`
(`WARNING_FRACTION = 0.80`, `:10`). Spend is per-UTC-month (`watchlist_budget_usage`, `models.py:138`).
`read_figures(session, watchlist)` (used in `routes_watchlists.py:29`) returns `(budget_status, spend)`.
`scheduling/budget_policy.py` calls these — do NOT recompute budget logic. Gate ONLY drafting steps; never
gate detection/escalation (Constitution III; FR-019b; SC-012).

---

## 9. Eval gate — `eval_thresholds.yaml` + CI `eval` job

Current `eval_thresholds.yaml` has `classifier/rag/triage/agent` blocks. ADD:
```
scheduling:
  due_selection_precision_min: 1.0
  due_selection_recall_min: 1.0
  duplicate_rate_max: 0
  loss_rate_max: 0
  transient_retry_recovery_min: 1.0
  inline_vs_durable_parity_min: 1.0
```
CI `eval` job (`.github/workflows/ci.yml:91-115`) runs gates as pytest/python steps. ADD two steps:
`uv run pytest tests/integration/test_scheduling_reliability.py -v` and
`PYTHONPATH=. uv run python eval/scheduling/run_due_selection_eval.py`. The reliability suite needs the DB
(it's in the integration set) — gate it consistently with the existing triage eval step (which also runs
pytest). Confirm whether the `eval` job has Postgres available; the triage eval step implies app deps are
synced (`uv sync --no-group training`) but **may not** have a live DB — if not, run the reliability suite
in the main `test` job instead and keep only the due-selection (pure-Python, no DB) step in `eval`.

---

## 10. What DOES NOT EXIST yet (build these)

❌ `app/jobs/` package (enqueue, context, tasks, retry, dead_letter, scheduler) ·
❌ `app/scheduling/` package (models, service, due, budget_policy) ·
❌ `watchlist_cycles`, `dead_letter` tables · ❌ `index_build_runs.watchlist_id` ·
❌ `watchlists.budget_exceeded_policy` · ❌ `JobDeadLettered` / `WatchlistBudgetThresholdReached` events ·
❌ `GET /admin/dead-letters`, `POST /admin/dead-letters/{id}/resolve`, cycle-status route, **cycle abandon
route** (`POST .../cycles/{id}/abandon` → sets `resolved_at`, clears the FR-018a exclusion) ·
❌ `watchlist_cycles.resolved_at` (the unresolved-`failed` exclusion in due-selection — see §below) ·
❌ `PermanentJobError` · ❌ ARQ real `functions`/`cron_jobs` (skeleton has only `heartbeat`/`[]`) ·
❌ worker `dispatcher`/`session_factory`/`register_audit_handlers` · ❌ `eval/scheduling/` ·
❌ `tests/integration/test_scheduling_reliability.py`, `tests/unit/test_due_selection.py`,
`tests/unit/test_budget_policy.py`.

---

## 10b. Cross-cutting gotchas surfaced by `/speckit-analyze` (G1–G5)

- **G1 — manual consolidate is INLINE today.** `app/reports/routes.py:259` does `report = await
  consolidate_batch(...)` synchronously in the request (not a BackgroundTask — so it's not one of the "5
  sites"). FR-001 requires it durable: convert to `enqueue("task_consolidate", ...)` → `202` (T033a).
  ⚠️ API contract change (sync report → 202) — verify the spec-10 admin console consolidate trigger.
- **G2 — manual index vs cycle index are DIFFERENT.** Manual (site 2, T019) = client-wide,
  `watchlist_id=None`, job_id `index:{client_id}:manual:{run_id}`. Cycle (T028/T033) = watchlist-scoped,
  job_id `index:{client_id}:{watchlist_id}:{cycle_id}`. Do NOT conflate them; the manual endpoint stays
  client-wide.
- **G3 — reconcile vs ARQ retry.** `lifespan.py:34-44 reconcile_interrupted_runs` marks lingering
  `running` ingestion runs FAILED on startup (spec-4 assumption: lost). Under ARQ they are **retried**, not
  lost — reconcile must not fail a run that has a live/queued ARQ job (T024a). Otherwise: failed row + a
  retried job writing to it = inconsistent state.
- **G4 — expedited revision.** The auto fan-out (site 5) is the first draft → `expedited:{finding_id}:0`
  (a `Finding` has no `revision` field). Redraft uses `redraft:{report_id}:{revision}` where revision =
  `report.revision_count`.
- **G5 — see §4** (enqueue dual-context).

## 11. Commands

```powershell
# Unit (no Docker)
uv run pytest tests/unit -v
# Integration (compose up + PANTERA_INTEGRATION=1 + localhost:5433/6380 per dev-environment.md)
uv run pytest tests/integration/test_scheduling_reliability.py -v
# Worker
uv run arq worker.worker.WorkerSettings
# Lint — BOTH must pass
uv run ruff check app worker tests ; uv run black --check app worker tests
```

Conventional Commits, **NO Co-Authored-By**. Keep files ≤~300 lines (split `app/jobs/*` by concern).
On this Windows host, integration tests need the gitignored `docker-compose.override.yml` (5433/6380) +
the Vault repoint described in `memory/host-integration-test-vault-repoint.md`.
