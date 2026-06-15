# Phase 1 Data Model — Frontend SPA (Spec 010)

This feature introduces **one** new persistent entity (`llm_usage`). Everything else is **consumed**
from existing spec 3/6/7/8/9 tables. The SPA holds no persistent server data (only browser-local
JWT + acting-client selection).

---

## New entity

### `llm_usage` (migration `0009`)

One row per **external** LLM call (triage valence/resolve + agent drafting). Drives the admin cost
dashboard (FR-021/033/034). Written best-effort by `record_usage()` — a write failure is logged and
swallowed, never failing the pipeline op (FR-033).

| Column | Type | Null | Notes |
|--------|------|------|-------|
| `id` | BigInteger PK | no | autoincrement |
| `client_id` | BigInteger FK → `clients.id` ON DELETE CASCADE | no | tenant scope (Principle V) |
| `finding_id` | BigInteger FK → `findings.id` ON DELETE SET NULL | yes | present for triage + expedited agent calls; null where N/A |
| `call_site` | String(8) | no | CHECK in (`'triage'`,`'agent'`) |
| `model` | String(64) | no | pinned model id used (e.g. `claude-3-5-sonnet-20241022`) |
| `input_tokens` | Integer | no | default 0 |
| `output_tokens` | Integer | no | default 0 |
| `cost_usd` | Numeric(12,6) | no | `input_tokens/1000*price_in + output_tokens/1000*price_out`; **Decimal** (not float) so SC-011 sums reconcile |
| `created_at` | DateTime(tz) | no | `server_default=func.now()` |

**Indexes**: `ix_llm_usage_client_id (client_id)`, `ix_llm_usage_client_created (client_id, created_at)`
(supports per-client dashboard aggregation + time windows).

**No PII / secrets** (FR-035): only counts, model id, derived cost, ids, timestamp. No prompt/response
text is stored.

**ORM**: `app/observability/models.py:LlmUsage(Base)` — mirror the column set above; add the two
`CheckConstraint`/`Index` entries in `__table_args__` (same style as `app/reports/models.py`).

---

## Consumed entities (existing — do NOT recreate; pinned for the implementer)

### `Report` — `app/reports/models.py` (table `reports`, migration 0008)
- `structured_fields: JSONB` = **list of claims** `[{text, provenance, source_ref?}]` (NOT
  field-keyed). `provenance ∈ {drafted_grounded, reviewer_attested, aggregated}`.
- `corroboration_count: int`, `corroboration_sources: JSONB|null`, `reviewer_comments: JSONB list`
  (rejection history), `revision_count: int`.
- `status ∈ {drafted, under_review, approved, rejected, discarded, needs_manual_revision}` — **no
  sent/delivered** (FR-006b forward dependency to spec 13).
- `report_type ∈ {expedited, batch}`, `sla_deadline?`, `watchlist_id?`, `cycle_period_start/end?`.

### `ReportFinding` — `app/reports/models.py` (table `report_findings`)
- `report_id`, `finding_id`, `client_id`, `report_type`, `state ∈ {included, dropped, discarded}`.
- Join to `Finding` (below) for drug/reaction/bucket in the FR-031 findings endpoint.

### `Finding` — `app/triage/models.py` (table `findings`, migration 0007)
- Provides `drug`, `reaction`, `bucket ∈ {emergency, urgent, minor, positive}`, `status`, `client_id`.

### `Chunk` — `app/embedding/models.py` (table `chunks`, migration 0006)
- `id` (← a claim's `source_ref` is `str(chunk.id)`; corroboration sources carry
  `passage_chunk_ids: list[int]`), `client_id`, `document_id`, `text`, `section`,
  `source_reliability`, `date`. Source of the FR-029 passage text.

### `Document` — `app/ingestion/models.py` (table `documents`)
- Join target for passage metadata (title, external_id). Confirm exact column names at implement
  time (`title`, `external_id`) via the ingestion models before writing the join.

### `Client` / `Watchlist` — specs 3/4b
- Admin-console CRUD reuses existing client-scoped routes; portal grouping uses `watchlist_id`
  (with `document_watchlists` junction attribution for expedited reports lacking a direct link).

### `User` — `app/auth/models.py`
- `user_type ∈ {staff, client}`; `role ∈ {manager, admin, reviewer}` (staff) or client-user;
  `client_id` (client-users scoped to one). Drives SPA role-routing + the acting-client switcher.

---

## State transitions (reference — owned by spec 9, surfaced by the SPA, NOT re-implemented)

```
drafted ──approve──────────────► approved (terminal*)
drafted ──edit-approve─────────► approved (terminal*)
drafted ──reject (n<3)─────────► drafted (redraft, revision_count++)
drafted ──reject (4th)─────────► needs_manual_revision (stays in queue, no auto-redraft)
drafted ──discard──────────────► discarded (terminal)
batch: finding drop ──► finding state=dropped (re-eligible next cycle)
batch: finding discard ──► finding state=discarded (permanent)
batch: all findings removed ──► report auto-discarded
```
\* `approved` is terminal **today**; spec 13 will extend with `sent`/`delivery_failed` + `delivered_at`.

The SPA invokes the existing action endpoints (`approve`/`edit-approve`/`reject`/`discard`,
finding `drop`/`discard`) and **renders** these transitions — it owns none of the state logic.

---

## Cost-dashboard aggregate (derived, not stored)

`GET /clients/{id}/usage` computes from `llm_usage` (FR-021/034):
- per-client totals: `sum(cost_usd)`, `sum(input_tokens)`, `sum(output_tokens)`, call count;
- a breakdown by `call_site` (triage vs agent) and optionally by `model`;
- optional time-window filter (`from`/`to` on `created_at`).
Empty result ⇒ explicit empty-state payload (zeros), not an error (FR-021).

## Operations-dashboard aggregate (derived, FR-021a — no new table)

`GET /clients/{id}/metrics` is computed live from existing `reports`/`findings`: report counts by
`status`, pending-queue split by `report_type`, expedited SLA buckets (overdue/due-soon/met from
`sla_deadline`), and redraft health (`revision_count` avg + count at `needs_manual_revision`/cap).
**No schema change.** The `delivery` block is `null` ("pending delivery layer") until spec 13 adds the
delivery states (forward dependency). See contracts/backend-endpoints.md → FR-021a.
