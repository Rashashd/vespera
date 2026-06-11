# Contract: Index-Build Trigger

`POST /clients/{client_id}/index` — start (or join) an index build for a client. Mirrors the Spec-4
ingestion trigger (FR-017, FR-026, FR-027, D12).

## Auth & scoping
- Requires authenticated **staff `manager` or `admin`** (`require_admin`). Staff `reviewer` and any
  client-user → **403 FORBIDDEN** (FR-027).
- `acting_client(client_id)` validates the target client: **404 CLIENT_NOT_FOUND** if absent (or, for
  a client-user, not their own); **400 CLIENT_SUSPENDED** if the client is not active (stops new work,
  FR-020).

## Request
- Path: `client_id` (int). No body.

## Behavior
- If a build is already `running` for this client → **no-op**, return the in-flight run (FR-026/D10).
- Otherwise create an `index_build_runs` row (`status=running`), dispatch `IndexBuildTriggered`
  (audit), commit, then schedule the runner via `BackgroundTasks` (session committed **before**
  `add_task` — BG-task/session-timing pattern).

## Responses
| Status | When | Body |
|--------|------|------|
| **202 Accepted** | build started, or an in-flight build was joined | `IndexBuildRunOut` |
| 400 | client suspended | `{"detail": "CLIENT_SUSPENDED"}` |
| 401 | unauthenticated | — |
| 403 | not manager/admin | `{"detail": "FORBIDDEN"}` |
| 404 | client not found / not visible | `{"detail": "CLIENT_NOT_FOUND"}` |

`IndexBuildRunOut`: `{id, client_id, status, started_at, finished_at, documents_processed,
chunks_created, documents_skipped, documents_errored}`.

## Invariants
- At most one `running` run per client at any time (partial unique index).
- No chunk for client A is ever produced under client B (FR-014).
- The endpoint never blocks on the actual build (runs in the background).
