# Contract: Per-Watchlist Batch Consolidation

Client-scoped under `/clients/{client_id}/...` via `acting_client()`. Triggers the one-batch-per-watchlist-per-cycle consolidation in spec 9 (durable cron wrapping = spec 11, which calls this same path).

## Consolidate a watchlist's pending-batch findings

`POST /clients/{client_id}/watchlists/{watchlist_id}/consolidate-batch`

- **Role:** staff (`manager`/`admin`). (Approval of the resulting batch is still `reviewer`-only via the reviewer-actions contract.)
- **Behavior:**
  1. Select `findings.status='pending_batch'` whose `document_id ∈ document_watchlists(watchlist_id)` (research D2), client-scoped.
  2. **Idempotent claim:** flip each to `processing` then `reported`, link via `report_findings`, so a finding already claimed by another of the client's watchlists is not double-reported (first-watchlist-wins).
  3. If zero claimable findings → **no report created** (FR-013); returns `204 No Content`.
  4. Otherwise build exactly **one** `batch` report: executive summary (count, corroboration highlights), positive section, minor section grouped by reaction type, per-finding detail with full source lists (FR-012). Status `drafted`; enters the reviewer queue as one item. Emits `BatchConsolidated` + `ReportDrafted`.
- **Idempotency:** a second call with nothing newly pending creates no duplicate (partial unique `ux_reports_batch_cycle`); returns the existing open batch or `204` (SC-008, FR-030).

- **201** → `ReportResponse` (the batch).
- **204** → no pending-batch findings (no report).
- **403** → caller lacks staff role.
- **404** → watchlist not in the acting client.

## Cycle window definition

The cycle window = the watchlist's findings in `pending_batch` since that watchlist's last batch report. There is **no** wall-clock cycle in spec 9; the window is defined by what is pending. Cadence-scheduled invocation (`daily`/`weekly`/`biweekly`/`monthly`) is spec-11, calling this endpoint per watchlist.

## Notes

- Cross-watchlist within a client: a finding whose document is on multiple watchlists is reported by whichever watchlist consolidates first (research D2). Cross-**client** isolation is absolute (FR-028).
- `biweekly` is a valid cadence as of migration 0008 but the scheduler that honors it is spec-11; here cadence is metadata only.
