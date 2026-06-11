# Contract: Index-Build Run & Document State Reads

Observability for the index build (FR-010). Read-only; uses `acting_client_read` (suspended clients
readable). Cross-tenant access returns **404** (never leaks existence), matching Spec-4 run reads.

## `GET /clients/{client_id}/index-runs`
List builds for a client, newest first.
- Query: `limit` (default 50), `offset` (default 0).
- Auth: staff (any role) or the owning client-user, via `acting_client_read`.
- 200 → `IndexBuildRunOut[]`.

## `GET /clients/{client_id}/index-runs/{run_id}`
One build's detail.
- 200 → `IndexBuildRunOut`.
- 404 RUN_NOT_FOUND if the run does not belong to this client (tenant isolation, SC-002).

## `GET /clients/{client_id}/index-state` (document index states)
Per-document index status for the client (supports operators inspecting skipped/errored documents).
- Query: `status` (optional filter ∈ DocumentIndexStatus), `limit`, `offset`.
- 200 → `DocumentIndexStateOut[]` = `{document_id, status, chunk_count, embedder_version, attempts,
  updated_at}`; `last_error` included for staff.

## Invariants
- Every returned row's `client_id` equals the path `client_id` (FR-014).
- Counts in `IndexBuildRunOut` reconcile: `documents_processed = indexed + indexed_empty`;
  `documents_skipped` counts already-`indexed`/`errored_permanent` seen; `documents_errored` counts
  this run's transient + permanent failures (FR-010).
