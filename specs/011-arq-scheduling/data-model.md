# Data Model: Durable ARQ Job Orchestration & Cron Scheduling

**Migration**: `0010_scheduling.py` · **down_revision = "0009"** (current head; verified
`app/db/migrations/versions/0009_llm_usage.py` is latest). One migration bundles all four changes below.

All timestamps are `DateTime(timezone=True)`, UTC. All `*_id` are `BigInteger` FKs matching existing
conventions (`clients.id`, `watchlists.id`, `findings.id`, `reports.id`, `index_build_runs.id`).

---

## 1. NEW TABLE — `watchlist_cycles`

One row per automated monitoring cycle for a watchlist (FR-016). Source of due-ness and the overlap guard.

| Column | Type | Notes |
|---|---|---|
| `id` | BigInteger PK | |
| `watchlist_id` | BigInteger FK → watchlists.id | `ondelete="CASCADE"` |
| `client_id` | BigInteger FK → clients.id | denormalized for tenant-scoped queries (matches `findings`/`reports`) |
| `status` | String(16) | CHECK `in ('in_progress','completed','failed')` |
| `current_stage` | String(24) | CHECK `in ('ingestion','index','triage','expedited','consolidation','done')`; the stage in flight / last reached |
| `cadence_at_start` | String(16) | snapshot of the watchlist cadence when the cycle began (cadence change mid-cycle does not retarget; spec Edge Cases) |
| `period_start` | DateTime(tz) | cycle window start (used for consolidation + the `cycle-start` idempotency key) |
| `period_end` | DateTime(tz) | cycle window end |
| `ingestion_run_id` | BigInteger FK → ingestion_runs.id, nullable | `ondelete="SET NULL"`; provenance |
| `index_build_run_id` | BigInteger FK → index_build_runs.id, nullable | `ondelete="SET NULL"`; provenance |
| `skipped_reason` | String(32), nullable | e.g. `budget_pause`, `budget_critical_only` (FR-019d) — what drafting was skipped & why |
| `failure_stage` | String(24), nullable | stage at which a `failed` cycle died (FR-018) |
| `resolved_at` | DateTime(tz), nullable | set when an operator **abandons** a `failed` cycle (FR-018b); a `failed` cycle with `resolved_at IS NULL` excludes the watchlist from auto-scheduling (FR-018a) |
| `started_at` | DateTime(tz) | server_default now() |
| `completed_at` | DateTime(tz), nullable | set on `completed` **or** terminal `failed` close-out; due-ness uses completion of a `completed` row |
| `updated_at` | DateTime(tz) | |

**Indexes / constraints**
- `ix_watchlist_cycles_watchlist_id` on `(watchlist_id)`.
- `ix_watchlist_cycles_client_id` on `(client_id)`.
- **Partial unique** `uq_watchlist_cycles_in_progress` on `(watchlist_id)` `WHERE status = 'in_progress'`
  — at most one open cycle per watchlist (FR-017; mirrors the `index_build_runs` partial-unique pattern at
  `0006_chunks_index_state.py:127`).

**Due-ness query (FR-013/FR-018a, conceptual).** A watchlist is due when ALL hold: its client is
`active`; the watchlist `is_active` and has items; there is **no** `in_progress` cycle; there is **no
unresolved `failed` cycle** (a `status='failed'` row with `resolved_at IS NULL` — FR-018a); and either no
`completed` cycle exists or `now - max(completed_at where status='completed') ≥ interval(cadence)`.
⚠️ The unresolved-`failed` exclusion is REQUIRED — without it a `failed` cycle (not `completed`) leaves the
watchlist looking due and it would auto-restart, violating FR-018a. Coalescing (FR-015b) is automatic:
overdue-by-N still yields one due row → one cycle. **Cadence intervals:** daily=1 day, weekly=7 days,
biweekly=14 days, **monthly = add one calendar month** (not a fixed 30 days), all computed in UTC.

**State transitions**: `in_progress` → `completed` (consolidation done) | `failed` (a stage dead-letters,
FR-018). `failed` is terminal for auto-scheduling (FR-018a); operator recovery (FR-018b) starts a new
cycle or resumes the failed stage manually.

---

## 2. NEW TABLE — `dead_letter`

One row per job that exhausted its retries (FR-009). Free of PII/secrets (FR-011).

| Column | Type | Notes |
|---|---|---|
| `id` | BigInteger PK | |
| `job_name` | String(48) | ARQ function name, e.g. `task_run_ingestion` |
| `job_key` | String(128) | the deterministic logical key (D3), e.g. `consolidate:{cycle_id}` |
| `client_id` | BigInteger FK → clients.id, nullable | `ondelete="SET NULL"`; tenant attribution |
| `args_digest` | String(64) | SHA-256 of the **non-PII** arg identifiers only (ids/keys, never payloads) |
| `error_class` | String(80) | exception class name (no message body that could carry PII) |
| `error_summary` | Text, nullable | redacted/truncated reason; MUST be scrubbed of PII/secrets |
| `attempts` | Integer | total tries made |
| `first_failed_at` | DateTime(tz) | |
| `dead_lettered_at` | DateTime(tz) | server_default now(); retention measured from here (FR-009a) |
| `resolved_at` | DateTime(tz), nullable | set when an operator re-triggers/abandons (dashboard surfacing filters on NULL) |

**Indexes**: `ix_dead_letter_client_id` on `(client_id)`; `ix_dead_letter_dead_lettered_at` on
`(dead_lettered_at)` (retention purge + dashboard ordering); partial `ix_dead_letter_unresolved` on
`(dead_lettered_at) WHERE resolved_at IS NULL`.

**Retention (FR-009a)**: default 90 days (`Settings.dead_letter_retention_days`), purged by a daily cron;
purge MUST NOT delete the corresponding `audit_log` rows.

---

## 3. ALTER — `index_build_runs` (watchlist-scoped index step, D7)

From `0006_chunks_index_state.py:90-133`. Deliberate change to a prior-spec table; pinned in
implementation-notes.

- **ADD** column `watchlist_id` `BigInteger` **nullable**, FK → `watchlists.id` `ondelete="CASCADE"`.
  NULL = the existing client-wide manual rebuild (preserved); non-NULL = a cadence-cycle scoped build.
- **ADD** index `ix_index_build_runs_watchlist_id` on `(watchlist_id)`.
- **DROP** `uq_index_build_runs_client_running` (unique on `(client_id) WHERE status='running'`).
- **CREATE** `uq_index_build_runs_client_wl_running` — unique on `(client_id, watchlist_id) WHERE
  status='running'` so per-watchlist cycle builds don't collide, while still bounding the manual
  client-wide build (watchlist_id NULL participates as its own slot).

> ⚠️ Postgres treats NULLs as distinct in unique indexes — two `watchlist_id IS NULL` running rows would
> NOT collide. The client-wide manual build already self-guards via `IndexBuildService.create_run`'s
> select-existing logic; keep that guard. Documented in implementation-notes.

---

## 4. ALTER — `watchlists` (budget-exceeded policy, D9)

From `0003_clients_watchlists.py` (cadence/budget live here; `0008` widened cadence CHECK).

- **ADD** column `budget_exceeded_policy` `String(16)` `nullable=False` `server_default='continue'`,
  CHECK `in ('continue','critical_only','pause')` (FR-019a).

No change to `budget_amount` / `watchlist_budget_usage` (reused as-is; `derive_budget_state` in
`app/clients/_helpers.py` already computes ok/warning/exceeded for the current UTC month).

---

## New domain event (no migration; code only)

`app/domain/events.py`:

```text
JobDeadLettered(DomainEvent):   # actor_id=0, actor_type="system"
    job_name: str = ""
    job_key: str = ""
    attempts: int = 0
    error_class: str = ""
```

Auto-registered by `register_audit_handlers` (walks `DomainEvent.__subclasses__()`). `_target_for` in
`app/audit/handler.py` will fall through to the class name unless a recognised id attr is added — acceptable
(target = `JobDeadLettered`); optionally extend `_target_for` to map `job_key`. A budget-transition event
(`WatchlistBudgetThresholdReached`, system actor, with `watchlist_id`) is added the same way for FR-019c.

## ORM placement

- `WatchlistCycle`, `DeadLetter` → `app/scheduling/models.py`.
- `budget_exceeded_policy` → add to `Watchlist` in `app/clients/models.py`.
- `index_build_runs.watchlist_id` → add to the `IndexBuildRun` model (locate via implementation-notes).
