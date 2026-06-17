# Phase 1 Data Model — Report Delivery & Final Wiring

Migration **`0012_delivery.py`**, `down_revision = "0011"` (head verified = `0011_rls_policies`). Follow the structure of `0010_scheduling.py` / `0011_rls_policies.py` (see [implementation-notes.md](./implementation-notes.md)). All new client-scoped data MUST be RLS-policied (Constitution V).

## 1. `ReportStatus` enum (extend) — `app/reports/enums.py`

Add three delivery states to the existing `drafted/under_review/approved/rejected/discarded/needs_manual_revision`:

| New value | Meaning |
|-----------|---------|
| `sent` | Dispatched to n8n; awaiting per-channel confirmation |
| `delivered` | All configured channels confirmed (terminal) |
| `delivery_failed` | A channel failed after retries, or the no-callback window elapsed |

`is_terminal` should treat `delivered` (and existing `approved`/`discarded`) appropriately; `delivery_failed` is **not** terminal (re-send allowed). Migration widens the `ck_reports_status` CHECK constraint (drop + recreate, per the 0008/0010 pattern) to include the three values.

## 2. `reports` table — new columns (`app/reports/models.py`)

| Column | Type | Null | Notes |
|--------|------|------|-------|
| `sent_at` | `timestamptz` | yes | When dispatch to n8n occurred |
| `delivered_at` | `timestamptz` | yes | Set when all configured channels confirm (FR-004) |
| `delivery_failed_at` | `timestamptz` | yes | Set on failure / no-callback sweep |
| `delivery_error` | `text` | yes | Short, PII-free failure summary (redacted) |
| `sla_escalation_tier` | `smallint` | no (default 0) | 0 = none, 1 = reviewers notified, 2 = manager/admin notified |
| `sla_escalated_at` | `timestamptz` | yes | Last escalation time (gates "at most once per tick") |

`sla_deadline` already exists (`app/reports/models.py:44`). No `delivered`/`sent` columns beyond status + these timestamps. **No suspension-tracking column** (D5 — cycles gate on client status).

## 3. `delivery_attempt` table — NEW (`app/delivery/models.py`)

One row per `(report_id, channel)` dispatch; the report's overall delivery status is **derived** from its attempts (D2/FR-004a).

| Column | Type | Null | Notes |
|--------|------|------|-------|
| `id` | `bigint` PK | no | autoincrement |
| `report_id` | `bigint` FK→`reports.id` (CASCADE) | no | |
| `client_id` | `bigint` FK→`clients.id` (CASCADE) | no | denormalized for RLS + scoping |
| `channel` | `varchar(8)` | no | CHECK `IN ('email','sftp')` |
| `recipient_kind` | `varchar(8)` | yes | `regular`/`urgent` (email) |
| `status` | `varchar(12)` | no | CHECK `IN ('pending','delivered','failed')`, default `pending` |
| `error` | `text` | yes | PII-free (redacted) |
| `dispatched_at` | `timestamptz` | no | server_default now() |
| `confirmed_at` | `timestamptz` | yes | delivered/failed callback time |

**Indexes**: `ix_delivery_attempt_report_id`; unique `ux_delivery_attempt_report_channel (report_id, channel)` (idempotency key for callbacks, D3); `ix_delivery_attempt_client_id`.

**RLS**: add `delivery_attempt` to the tenant-isolation policy set in migration 0012 (mirror `0011_rls_policies.py`: `ENABLE` + `FORCE ROW LEVEL SECURITY` + `CREATE POLICY tenant_isolation ... USING (...) WITH CHECK (...)`). Worker writes run under system context (`install_system_rls`); API request paths set per-principal context.

## 4. `clients` table — SFTP destination columns (`app/clients/models.py`)

Email recipients already exist (`report_email_regular`/`report_email_urgent`, lines 33-34). Add SFTP **destination metadata only** (credential lives in n8n, D7):

| Column | Type | Null | Notes |
|--------|------|------|-------|
| `sftp_enabled` | `boolean` | no (default false) | Whether SFTP is a configured channel |
| `sftp_host` | `varchar(255)` | yes | Destination host |
| `sftp_path` | `varchar(512)` | yes | Destination directory/path |
| `sftp_username` | `varchar(255)` | yes | For n8n credential lookup; not a secret |

"Configured channel" (FR-003): email = a non-null recipient for the report's urgency; SFTP = `sftp_enabled` true with host+path. Deliver to every configured channel.

## 5. `DeliveryMetrics` schema — `app/observability/schemas.py`

Replace `OpsDashboard.delivery: None` with `delivery: DeliveryMetrics | None`:

| Field | Type | Notes |
|-------|------|-------|
| `sent` | int | reports currently `sent` (awaiting confirmation) |
| `delivered` | int | reports `delivered` in window |
| `failed` | int | reports `delivery_failed` in window |
| `success_rate` | float | `delivered ÷ dispatched` in window (FR-011); 100.0 when none |

Populated in `app/reports/metrics_routes.py` from `reports` status counts (+ `delivery_attempt` if per-channel detail is wanted). Frontend `OpsDashboardSchema` (`frontend/src/api/schemas.ts`) updates `delivery` from `z.null()` to the object.

## 6. Domain events — NEW (`app/domain/events.py`)

Frozen dataclasses extending `DomainEvent` (consumed by the audit handler automatically):

| Event | Fields (beyond actor/client) | Raised by |
|-------|------------------------------|-----------|
| `ReportDispatched` | `report_id`, `channels: list[str]` | delivery job after enqueue→send |
| `ReportDelivered` | `report_id` | callback when all channels confirm |
| `ReportDeliveryFailed` | `report_id`, `channel`, `reason` | callback failure / no-callback sweep |
| `ReportDeliveryHeld` | `report_id`, `reason` (`no_channel`/`suspended`) | hold path (FR-007/007a) |
| `ReportResent` | `report_id`, `channels: list[str]` | staff re-send |
| `SlaEscalated` | `report_id`, `tier: int` | sweep escalation |
| `AuditExported` | `format`, `scope` | audit export endpoint |
| (reuse) `WatchlistBudgetThresholdReached` | existing | budget notification handler (US6) |

Every event names a server-validated `client_id` → one append-only `audit_log` row (FR-008/026). Keep `reason`/`error` fields PII-free (scrub via `app/redaction`).

## 7. Reused entities (NO change)

- **`audit_log`** (`app/audit/models.py`) — RLS-exempt, append-only; sink for all delivery/notification/export events; source for the export.
- **`dead_letter`** (`app/scheduling/models.py`) — feeds the new `DeadLetterCard` (US7); no change.
- **Staff/Client users** (`app/auth/models.py`) — managed by the new account screens (US4); no model change (creation endpoints + `password` field already exist).
- **`watchlists.budget_exceeded_policy`** (`app/clients/models.py:73`) — already set via the existing UI control (FR-020 verify-only).

## State transitions (report delivery)

```text
approved ──(dispatch all configured channels)──▶ sent
   │                                               │
   │ (no channel configured / client suspended)    ├─ all channels delivered ──▶ delivered  [delivered_at]
   ▼                                               ├─ any channel failed (after retries) ─▶ delivery_failed
approved (held; alert)                             └─ no callback within window (sweep) ──▶ delivery_failed
   │ (channel configured / reactivated + re-send)
   └────────────────────────────────────────────▶ sent

delivery_failed ──(admin/manager re-send: failed channels only)──▶ sent ──▶ delivered
```

Overall status is always derived from `delivery_attempt` rows (delivered = all attempts delivered; failed = any attempt failed). Re-send creates/re-opens attempts only for unconfirmed/failed channels and never re-sends a confirmed channel (FR-004a/006).
