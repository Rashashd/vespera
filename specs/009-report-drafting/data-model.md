# Phase 1 Data Model: Report Drafting

Migration **0008** (`0008_reports_and_followups.py`, down_revision = `0007`). All new rows carry `client_id` (Principle V). Field types target PostgreSQL. ORM lands in `app/reports/models.py`; enums in `app/reports/enums.py`.

---

## Modified: `findings` (spec 8, table exists)

Widen the status CHECK to add the reporting-lifecycle states. **No column added** (watchlist attribution is derived — research D2).

| Column | Change |
|--------|--------|
| `status` | CHECK widened to `('pending_expedited','pending_batch','classified','processing','reported','discarded')` |

- `corroboration_sources` (JSONB, already present) — populated by the agent's corroboration step at draft time.
- State transitions: `pending_expedited → processing → reported` (expedited); `pending_batch → processing → reported` (claimed by a watchlist batch) or `pending_batch → discarded` (discard-permanently) or back to `pending_batch` (drop-from-report). `→ discarded` is terminal (no auto-resurrect, FR-030).

## Modified: `watchlists` (spec 3, table exists)

| Column | Change |
|--------|--------|
| `cadence` | CHECK widened to `('daily','weekly','biweekly','monthly')` |

Mirror in `app/clients/enums.py:Cadence` → add `BIWEEKLY = "biweekly"`.

---

## New: `reports`

One drafted safety document for one client.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGINT PK | |
| `client_id` | BIGINT FK→clients ON DELETE CASCADE, NOT NULL | tenant boundary (Principle V) |
| `report_type` | VARCHAR(12) NOT NULL | CHECK `('expedited','batch')` |
| `status` | VARCHAR(24) NOT NULL | CHECK `('drafted','under_review','approved','rejected','discarded','needs_manual_revision')` |
| `structured_fields` | JSONB NOT NULL | named fields (Drug/Reaction/Population/Dose/Study type/Source reliability/Corroboration count/All sources/Causality/Recommendation) as a claim list, each claim `{text, provenance, source_ref?}` |
| `draft_body` | TEXT | rendered narrative (machine draft or reviewer-edited) |
| `corroboration_count` | INT NOT NULL DEFAULT 0 | distinct corroborating sources |
| `corroboration_sources` | JSONB | per-source citation metadata (title/identifier/date/passage_ref) |
| `revision_count` | INT NOT NULL DEFAULT 0 | redraft rounds used (cap 3, per report — incl. batch) |
| `reviewer_comments` | JSONB NOT NULL DEFAULT `'[]'` | append-only history `{reviewer_id, comment, ts, action}` |
| `sla_deadline` | TIMESTAMPTZ | expedited only (FR-005); window from `Settings` |
| `watchlist_id` | BIGINT FK→watchlists | batch only (the consolidating watchlist) |
| `cycle_period_start` / `cycle_period_end` | TIMESTAMPTZ | batch only |
| `created_at` / `updated_at` | TIMESTAMPTZ | |

**Constraints / indexes:**
- `ix_reports_client_id`, `ix_reports_status`, `ix_reports_client_status` (reviewer queue query).
- One-active-expedited-report-per-finding (FR-030) is enforced on **`report_findings`**, not `reports` (reports has no `finding_id` column): a partial unique on `report_findings(finding_id)` filtered to rows whose report is an active expedited report.
- Partial unique `ux_reports_batch_cycle` on `(watchlist_id, cycle_period_start)` where `report_type='batch'` and status not terminal — idempotent one-batch-per-watchlist-cycle (FR-011/030, SC-008).

## New: `report_findings`

Report↔finding junction; carries per-finding batch state (Q4 drop/discard) and the expedited 1:1 link.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGINT PK | |
| `report_id` | BIGINT FK→reports ON DELETE CASCADE, NOT NULL | |
| `finding_id` | BIGINT FK→findings ON DELETE CASCADE, NOT NULL | |
| `client_id` | BIGINT NOT NULL | denormalized for isolation queries |
| `state` | VARCHAR(12) NOT NULL DEFAULT `'included'` | CHECK `('included','dropped','discarded')` |
| `created_at` | TIMESTAMPTZ | |

**Constraints / indexes:**
- `ux_report_findings_unique` on `(report_id, finding_id)`.
- `ux_report_findings_active_expedited` — partial unique on `(finding_id)` where the linked report is `report_type='expedited'` and status not terminal (enforces FR-030 expedited idempotency).
- `ix_report_findings_finding_id` (for "is this finding already reported?" idempotency, FR-030).
- Expedited: exactly one row per report. Batch: many rows; removing the last `included` row auto-discards the report (FR-013a).

## New: `report_followups`

Emergency author-outreach artifact. **Not** surfaced in the reviewer queue.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGINT PK | |
| `client_id` | BIGINT FK→clients ON DELETE CASCADE, NOT NULL | |
| `finding_id` | BIGINT FK→findings ON DELETE CASCADE, NOT NULL | the life-threatening finding |
| `report_id` | BIGINT FK→reports | the linked expedited report |
| `template_ref` | VARCHAR(64) NOT NULL | fixed form template identifier |
| `cover_message` | TEXT NOT NULL | auto-generated message summarizing the finding |
| `recipient_kind` | VARCHAR(8) | `author` \| `journal` placeholder; resolution deferred to delivery |
| `status` | VARCHAR(16) NOT NULL DEFAULT `'generated'` | sending deferred to delivery feature |
| `created_at` | TIMESTAMPTZ | |

**Index:** `ux_report_followups_finding` on `(finding_id)` (idempotent — one follow-up per emergency finding).

---

## Enums (`app/reports/enums.py`)

- `ReportType`: `expedited`, `batch`.
- `ReportStatus`: `drafted`, `under_review`, `approved`, `rejected`, `discarded`, `needs_manual_revision`.
- `ClaimProvenance`: `drafted_grounded`, `reviewer_attested`.
- `FindingReportState`: `included`, `dropped`, `discarded`.

## Report status state machine

```
drafted ──(reviewer opens)──► under_review
under_review ──Approve──────────────► approved        (terminal-for-this-feature; ready-to-send)
under_review ──Edit+Approve─────────► approved        (edited body persists; edits→reviewer_attested)
under_review ──Reject(comment)──────► drafted (redraft run, revision_count++)   [while revision_count < 3]
under_review ──Reject(4th)──────────► needs_manual_revision   (stays in reviewer queue)
under_review ──Discard──────────────► discarded        (terminal)
batch: last included finding removed ► discarded        (auto, FR-013a)
agent-side failure (pre-draft) ─────► (no report row) operator alert
```

## Domain events (`app/domain/events.py`)

Reuse `ReportApproved` (exists, line 27). Add: `ReportDrafted`, `ReportEdited`, `ReportRejected`, `ReportDiscarded`, `FindingDiscarded`, `ReportOperatorAlert`, `BatchConsolidated`. All carry `client_id`; report events carry `report_id`; finding/escalation events carry `finding_id`. Passive audit-log listener persists each (FR-021, SC-009).

## Settings additions (`app/core/config.py`, flat `Settings`)

| Setting | Default | Purpose |
|---------|---------|---------|
| `agent_max_iterations` | 8 | bounded loop cap (FR-022) |
| `agent_max_tokens` | 8000 | bounded token budget (FR-022) |
| `report_redraft_cap` | 3 | redraft rounds before `needs_manual_revision` (FR-016) |
| `expedited_sla_hours` | 24 | SLA deadline window (FR-005) |
| `agent_llm_max_tokens` | 2048 | per-call cap for draft/redraft |

(Thresholds for eval gates live in `eval_thresholds.yaml`, not here.)
