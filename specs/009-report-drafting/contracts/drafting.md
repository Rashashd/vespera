# Contract: Expedited Drafting Trigger & Agent Run

All routes are client-scoped under `/clients/{client_id}/...` and resolve the tenant via the existing `acting_client()` dependency (staff cross-client allowed + attributed; client-users own-client only). Request/response bodies are Pydantic (no ORM leakage). Auth via existing fastapi-users JWT.

## Trigger model (no public "draft now" endpoint required for the happy path)

Expedited drafting is **in-process**: after triage upserts an `urgent`/`emergency` finding, the triage path commits and schedules `app/reports/runner.py:draft_expedited(finding_id)` via `BackgroundTasks` (commit-before-add_task). There is no synchronous client-facing draft call on the hot path.

### Optional admin re-trigger (idempotent)

`POST /clients/{client_id}/findings/{finding_id}/draft`

- **Role:** staff (`manager`/`admin`/`reviewer`).
- **Behavior:** idempotently (re)drafts the expedited report for the finding. If an active report exists → returns it unchanged (FR-030). If the finding's prior report is terminal (`discarded`/`rejected`) → **does not** auto-resurrect; returns `409 Conflict` with `code=terminal_finding` (re-draft is an explicit manual action surfaced separately).
- **200/201** → `ReportResponse`.
- **422** → finding not in an expedited bucket.

## Agent run outcomes (internal contract for `app/agent/graph.py`)

A bounded run returns one of:
- `drafted` → a `reports` row in `drafted` status with grounded `structured_fields` + `corroboration_*`; for `emergency`, a `report_followups` row is also created.
- `operator_alert` → **no** report row; a `ReportOperatorAlert` event + `report.operator_alert` structured log (reason ∈ `ungroundable_no_evidence` | `loop_cap` | `token_cap` | `tool_failure`). Never surfaces in the reviewer queue.

Tools obey the `ToolError(error, retryable)` contract (never raise). Retryable → loop within `agent_max_iterations`; non-retryable or cap hit → `operator_alert`.

## ReportResponse (shared shape)

```
ReportResponse {
  id, client_id, report_type, status,
  structured_fields: [ { field, text, provenance, source_ref? } ],
  draft_body,
  corroboration_count, corroboration_sources: [ { title, identifier, date, passage_ref } ],
  revision_count, sla_deadline?, watchlist_id?, cycle_period?,
  findings: [ { finding_id, drug, reaction, bucket, state } ],
  created_at, updated_at
}
```

Grounding guarantee: every `structured_fields[*]` with `provenance=drafted_grounded` MUST carry a resolvable `source_ref` (SC-001).
