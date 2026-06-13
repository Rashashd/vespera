# Contract: Reviewer HITL Actions

All routes client-scoped under `/clients/{client_id}/...` via `acting_client()`. **Authorization: `reviewer` role only** (FR-019; `manager`/`admin` are refused with `403`). Every action emits a domain event recorded by the passive audit listener (FR-021, SC-009). Concurrency: actions take an optimistic version/status check — only the first decision on a report takes effect (`409 Conflict` on stale).

## Reviewer queue (drafts-only)

`GET /clients/{client_id}/reports?status=drafted|under_review|needs_manual_revision`

- **Role:** `reviewer`.
- Returns the drafts-only queue: `reports` rows in non-terminal review states. **Excludes** operator alerts and `report_followups` (the reviewer only ever sees written reports).
- **200** → `[ReportSummary]` (paginated; pass `?limit=` per the stale-data test lesson).

`GET /clients/{client_id}/reports/{report_id}`

- Returns the full `ReportResponse` including the **complete** citation set — all N corroborating sources per finding, each resolvable to its exact passage (FR-020, not just the top hit).

## Actions

`POST /clients/{client_id}/reports/{report_id}/approve`
- Body: none. Status `drafted|under_review → approved` (ready-to-send). Emits `ReportApproved`. **No** further drafting (FR-014/021, SC-002).

`POST /clients/{client_id}/reports/{report_id}/edit-approve`
- Body: `{ structured_fields?, draft_body? }`. Persists edited content as the approved report (FR-017); edited/added claims tagged `reviewer_attested`; grounding gate does **not** block edits. Emits `ReportEdited` + `ReportApproved`.

`POST /clients/{client_id}/reports/{report_id}/reject`
- Body: `{ comment: str }` (required). If `revision_count < report_redraft_cap (3)` → triggers a fresh bounded redraft run addressing the comment, `revision_count++`, comment appended to history, status returns to `drafted`. On the **4th** rejection → status `needs_manual_revision` (stays in reviewer queue, no further auto-redraft, FR-016). Emits `ReportRejected`.

`POST /clients/{client_id}/reports/{report_id}/discard`
- Status → `discarded` (terminal); no delivery possible. Emits `ReportDiscarded`.

## Per-finding actions within a batch report

`POST /clients/{client_id}/reports/{report_id}/findings/{finding_id}/drop`
- `report_findings.state → dropped`; finding returns to `pending_batch` (re-eligible next cycle for the same watchlist). Emits `FindingDiscarded(kind=drop)`. If this empties the batch (no `included` left) → report auto-`discarded` (FR-013a).

`POST /clients/{client_id}/reports/{report_id}/findings/{finding_id}/discard`
- `report_findings.state → discarded`; `findings.status → discarded` (terminal, never resurfaces). Emits `FindingDiscarded(kind=permanent)`. Same empties-batch → auto-discard rule.

## Error contract

| Code | When |
|------|------|
| `403` | non-`reviewer` role attempts any action |
| `404` | report/finding not in the acting client |
| `409` | stale status (concurrent action) or action invalid for current status |
| `422` | missing required `comment` on reject; invalid edit payload |
