# Contract — New/Changed Backend Endpoints (Spec 010)

All routes are async FastAPI, client-scoped under `/clients/{client_id}`, Pydantic at the boundary
(no ORM leakage). Auth deps from `app/auth/dependencies.py`. Errors use the existing
`HTTPException(detail="UPPER_SNAKE")` convention.

---

## FR-029 · Passage text resolution

`GET /clients/{client_id}/passages/{chunk_id}` — guard: `current_active_principal` +
`acting_client(allow_suspended=True)`.

**Why both staff and client-users may call it:** `acting_client` 404s a client-user on any client
that isn't their own, so this single route safely serves reviewers (acting client) and client-users
(own client). The chunk must also belong to the client (`Chunk.client_id == client.id`).

**200** `PassageResponse`:
```json
{
  "chunk_id": 123,
  "text": "full exact passage text …",
  "section": "Adverse Reactions",
  "source_reliability": "high",
  "date": "2025-03-01T00:00:00Z",
  "document_id": 45,
  "title": "Case report of …",
  "external_id": "PMID:39999999"
}
```
**404** `{"detail": "PASSAGE_UNAVAILABLE"}` — chunk missing or not this client's. The UI then shows
citation metadata + a "passage unavailable" state (FR-010), without failing the report view.

---

## FR-030 · Client portal report read path

Separate from the reviewer routes (those stay `require_reviewer`). Guard:
`current_active_principal` + `acting_client(allow_suspended=True)`. Status filter is applied
server-side: `Report.status IN ('approved','sent','delivered')` (only `approved` matches today).

`GET /clients/{client_id}/portal/reports?watchlist_id={id?}` → `list[PortalReportSummary]`
- Own-client, approved-or-later only. Optional `watchlist_id` filter (the portal renders one page per
  watchlist). Expedited reports lacking a direct `watchlist_id` are attributed to a single owning
  watchlist via the `document_watchlists` junction (deterministic first/claiming watchlist, matching
  spec 9 attribution).

`GET /clients/{client_id}/portal/reports/{report_id}` → `PortalReportDetail`
- Read-only detail; 404 if the report isn't this client's or isn't approved-or-later.

`PortalReportSummary` (portal-safe — omit reviewer-internal fields like `reviewer_comments`,
`revision_count`):
```json
{
  "id": 1, "report_type": "expedited", "status": "approved",
  "delivery_status": "approved_pending_delivery",
  "watchlist_id": 7, "corroboration_count": 3,
  "sla_deadline": null, "cycle_period_start": null, "cycle_period_end": null,
  "created_at": "…", "updated_at": "…"
}
```
`PortalReportDetail` = adds `structured_fields:[Claim]`, `draft_body`, `corroboration_sources`,
and the report's finding statuses (drug/reaction/bucket/state via FR-031 shape). NO decision controls
are implied — read only.

`delivery_status` is a derived label: `approved_pending_delivery` now; `sent|delivered|delivery_failed`
once spec 13 sets the underlying status (FR-006b). Compute it from `status`.

---

## FR-031 · Per-report findings

`GET /clients/{client_id}/reports/{report_id}/findings` → `list[ReportFindingDetail]` — guard:
`current_active_principal` + `acting_client(allow_suspended=True)`; the report must be this client's
(404 otherwise). Used by the reviewer batch drop/discard UI **and** the portal finding-status display.

Query: `ReportFinding` rows for `report_id` joined to `Finding` for drug/reaction/bucket.

`ReportFindingDetail`:
```json
{
  "id": 10, "report_id": 1, "finding_id": 55,
  "drug": "atorvastatin", "reaction": "rhabdomyolysis",
  "bucket": "urgent", "state": "included", "created_at": "…"
}
```
(`state ∈ {included, dropped, discarded}`; `bucket ∈ {emergency, urgent, minor, positive}`.)

---

## FR-006a · Reviewer all-reports listing (tweak, not a new route)

Extend `GET /clients/{client_id}/reports` (existing, `require_reviewer`) to accept `status=all`:
- `status` omitted → unchanged default `{drafted, under_review, needs_manual_revision}` (action queue).
- `status=all` → no status filter (every status — read-only history view).
- `status=<concrete>` → unchanged single-status filter.

~3-line change in `list_reports`. Reviewer-only; does not widen access to other roles.

---

## FR-021/034 · Cost/usage dashboard read

`GET /clients/{client_id}/usage?from={iso?}&to={iso?}` — guard: `require_admin` (manager/admin) +
`acting_client(allow_suspended=True)`. Aggregates `llm_usage` for the client **from the local table
only** (never LangSmith at view-time, FR-034).

**200** `CostDashboard`:
```json
{
  "client_id": 3,
  "total_cost_usd": "0.412300",
  "total_input_tokens": 81234,
  "total_output_tokens": 20111,
  "call_count": 57,
  "by_call_site": {
    "triage": {"cost_usd": "0.102000", "calls": 40},
    "agent":  {"cost_usd": "0.310300", "calls": 17}
  },
  "window": {"from": null, "to": null}
}
```
Empty (no usage yet) ⇒ zeros + `call_count: 0` (explicit empty state, **not** an error — FR-021).
`cost_usd` serialized as a fixed-precision string (Decimal) so the dashboard total reconciles exactly
with the summed records (SC-011).

---

## FR-021a · Operations dashboard metrics

`GET /clients/{client_id}/metrics?from={iso?}&to={iso?}` — guard: `require_admin` (manager/admin) +
`acting_client(allow_suspended=True)`. Aggregates **from `reports`/`findings`** (no new table; derived).

**200** `OpsDashboard`:
```json
{
  "client_id": 3,
  "by_status": {
    "drafted": 12, "under_review": 4, "approved": 140,
    "rejected": 6, "discarded": 9, "needs_manual_revision": 3
  },
  "queue": { "pending": 18, "expedited": 5, "batch": 13 },
  "sla": { "overdue": 2, "due_soon": 3, "met_pct": 95 },
  "redraft": { "avg_revisions": 0.6, "hit_cap": 3 },
  "delivery": null,
  "window": { "from": null, "to": null }
}
```
- `by_status` = report counts grouped by `reports.status`. `queue` = non-terminal counts split by
  `report_type`. `sla` from `sla_deadline` vs now on expedited reports (`due_soon` = within a small
  threshold, e.g. ≤2h). `redraft` from `revision_count` + count at `needs_manual_revision`/cap.
- **`delivery` is `null` ("pending delivery layer")** until spec 13 introduces sent/delivered/failed
  states — then it becomes `{ "sent": n, "delivered": n, "failed": n, "success_pct": … }`. **Forward
  dependency on spec 13** (same root as FR-006b). The UI renders the delivery card as a stub while null.
- Empty client ⇒ zeroed structure, not an error (explicit empty state, FR-021a).
- Cost is a separate call (`GET /clients/{id}/usage`, FR-021); the dashboard composes both.

---

## Authorization summary

| Endpoint | Reviewer | Manager/Admin | Client-user |
|---|---|---|---|
| `GET .../passages/{chunk_id}` | ✅ acting client | ✅ acting client | ✅ own client only |
| `GET .../portal/reports[...]` | ✅ acting client | ✅ acting client | ✅ own client, approved+ only |
| `GET .../reports/{id}/findings` | ✅ | ✅ | ✅ own client (for portal detail) |
| `GET .../reports[...]` (queue/all) | ✅ only | ❌ | ❌ |
| `GET .../usage` | ❌ | ✅ | ❌ |
| `GET .../metrics` | ❌ | ✅ | ❌ |

The per-client wall is enforced by `acting_client` (client-users → own client) on every row read.
