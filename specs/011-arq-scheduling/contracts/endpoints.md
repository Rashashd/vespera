# Contract: HTTP Endpoints (new / changed)

All routes follow existing conventions: `acting_client`/`get_acting_client` for `{client_id}` scoping,
role guards (`require_admin`/`require_reviewer`), Pydantic in/out (never return ORM), `session.begin()`
transactions, dispatch domain events for audit.

## Changed — trigger routes now enqueue durably (no behavior change to the API contract)

These four routes currently call `background_tasks.add_task(...)`; they switch to `enqueue(...)`. Request
bodies, response models, and status codes are **unchanged** (still 202 / summary models). Only the
execution mechanism changes (durable in prod, inline under `jobs_inline`).

- `POST /clients/{client_id}/watchlists/{watchlist_id}/ingest` (`routes_ingestion.py`)
- `POST /clients/{client_id}/index-build` (`embedding/routes.py`)
- `POST /clients/{client_id}/reports/{report_id}/reject` → redraft (`reports/routes.py`)
- `POST /clients/{client_id}/findings/{finding_id}/...` expedited trigger path (`reports/routes.py:343`)

**Changed — manual consolidate becomes async (G1, FR-001).** `POST
/clients/{client_id}/watchlists/{watchlist_id}/consolidate-batch` (`reports/routes.py:259`) currently
**awaits `consolidate_batch` inline and returns the report synchronously**. It MUST be converted to
`enqueue("task_consolidate", ...)` returning **`202`** (consistent with ingest/index manual triggers).
⚠️ **API contract change** (sync report → 202): verify/adjust the spec-10 admin-console manual-consolidate
trigger to handle 202 + refresh instead of expecting the report inline — recorded in the frontend
forward-dependency ledger.

## New — set watchlist budget-exceeded policy (FR-019a)

`PATCH /clients/{client_id}/watchlists/{watchlist_id}` (extend existing watchlist-update route) OR a
dedicated `PUT .../budget-policy`. Prefer extending the existing update route in
`clients/routes_watchlists.py` (it already handles cadence/severity/budget diffs + emits
`WatchlistConfigured`).

- Auth: `require_admin` (staff manager/admin), `get_acting_client`.
- Body: `{ "budget_exceeded_policy": "continue" | "critical_only" | "pause" }`.
- Effect: update column; emit the existing watchlist-config event with the diff.
- Response: the watchlist read model, now including `budget_exceeded_policy`.

## New — dead-letter / failed-jobs read (FR-021)

`GET /admin/dead-letters` (staff-only; manager/admin).
- Query: `?resolved=false` (default), `?client_id=`, pagination.
- Returns: list of dead-letter summaries (`job_name`, `job_key`, `client_id`, `error_class`, `attempts`,
  `dead_lettered_at`, `resolved_at`) — **no** payloads/PII.
- Powers the spec-10 admin dashboard failed-jobs card.

`POST /admin/dead-letters/{id}/resolve` (staff-only) — marks `resolved_at` (operator acknowledged /
re-triggered elsewhere). Re-triggering the actual work uses the existing manual stage endpoints
(FR-018b); this endpoint only clears it from the active surface.

## New — watchlist cycle status (operator visibility, optional but recommended)

`GET /clients/{client_id}/watchlists/{watchlist_id}/cycles` (staff; reviewer read-ok).
- Returns recent `watchlist_cycles` rows (`status`, `current_stage`, `period_*`, `skipped_reason`,
  `failure_stage`, `resolved_at`, timestamps) for cycle history / debugging and to back any future
  cycle-status UI.

`POST /clients/{client_id}/watchlists/{watchlist_id}/cycles/{cycle_id}/abandon` (staff `require_admin`).
- **Abandon a `failed` cycle** (FR-018b): sets `resolved_at`, clearing the FR-018a auto-scheduling
  exclusion so the watchlist returns to normal cadence at its next interval. No-op/409 if the cycle is not
  `failed`. Emits a system-actor domain event for audit.

## Out of scope (recorded forward deps)

- Active budget-threshold notification send → spec 13.
- Budget-policy **UI control** + dead-letter **dashboard card** wiring live in the frontend; backend
  fields/endpoints ship here (see frontend forward-dependency ledger).
