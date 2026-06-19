---
description: "Task list for 013-delivery implementation"
---

# Tasks: Report Delivery & Final Wiring Close-Out

**Input**: Design documents from `specs/013-delivery/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/delivery-api.md, **implementation-notes.md (READ FIRST)**

**Tests**: INCLUDED — the spec requires them (SC-010, FR-030 mandates the tracing unit test, ≥95% coverage on delivery DB-write/HITL-adjacent paths, the redaction gate, and the quickstart integration scenarios). n8n is **mocked** in tests; the callback endpoint is exercised directly.

**Organization**: Grouped by user story (US1–US8) for independent implementation/testing. **MVP = Phase 1 + 2 + 3 (US1).**

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no incomplete dependencies)
- **[Story]**: US1–US8 (setup/foundational/polish have no story label)
- Paths are repo-relative. Backend = `app/`, worker = `worker/`, SPA = `frontend/src/`.

⚠️ **Before coding, read `specs/013-delivery/implementation-notes.md`** — it pins verified file:line anchors and a "do-not-rebuild" inventory (e.g. `DeliveryStatusChip` and the budget-policy control already exist; `GET /audit` already exists).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Package skeleton + config, no behavior yet.

- [x] T001 [P] Create the `app/delivery/` package skeleton (`__init__.py` + empty `models.py`, `rendering.py`, `n8n_client.py`, `service.py`, `handlers.py`, `notifications.py`, `sweep.py`, `routes.py`), each with a one-sentence module docstring, in `app/delivery/`
- [x] T002 [P] Add optional delivery settings to `app/core/config.py`: `n8n_webhook_url: str = ""`, `delivery_callback_token: str = ""`, `delivery_no_callback_window_hours: int = 6`, `sla_tier2_interval_hours: int = 2`, `delivery_sweep_cron_minute: int = "*/15"`-equivalent. Do NOT add to `_REQUIRED_SECRETS`.
- [x] T003 [P] Register the optional `n8n_webhook_url` + `delivery_callback_token` secrets in `scripts/write_secrets.py` (local Vault) — NOT in `_REQUIRED_SECRETS`, NOT in `.github/workflows/ci.yml` (delivery degrades/holds when unset; app must still boot)

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ CRITICAL**: Blocks US1/US2/US3. No delivery work begins until the schema + states exist.

- [x] T004 Extend `ReportStatus` with `SENT`/`DELIVERED`/`DELIVERY_FAILED` and update `is_terminal` (delivered terminal; delivery_failed not) in `app/reports/enums.py`
- [x] T005 Author migration `app/db/migrations/versions/0012_delivery.py` (`revision="0012"`, `down_revision="0011"`): widen `ck_reports_status` (drop+recreate, 9 values); add `reports` columns `sent_at`/`delivered_at`/`delivery_failed_at`/`delivery_error`/`sla_escalation_tier`(default 0)/`sla_escalated_at`; add `clients` columns `sftp_enabled`(default false)/`sftp_host`/`sftp_path`/`sftp_username`; create `delivery_attempt` table + indexes + unique `(report_id, channel)`; add the tenant-isolation RLS policy for `delivery_attempt` (mirror `0011_rls_policies.py`) (depends T004)
- [x] T006 [P] Mirror the new `reports` delivery/SLA columns + widened status CHECK in the `Report` model in `app/reports/models.py`
- [x] T007 [P] Create the `DeliveryAttempt` ORM model (per `(report_id, channel)`; status pending/delivered/failed) in `app/delivery/models.py`
- [x] T008 [P] Add the SFTP destination columns to the `Client` model in `app/clients/models.py`
- [x] T009 [P] Add delivery/notification domain events (`ReportDispatched`, `ReportDelivered`, `ReportDeliveryFailed`, `ReportDeliveryHeld`, `ReportResent`, `SlaEscalated`, `AuditExported`) in `app/domain/events.py`
- [x] T010 Apply + verify migration on the live DB: `uv run alembic upgrade head` reaches `0012`, then verify `downgrade` is clean (`pantera_app` role must exist first) (depends T005, T006, T007, T008)

**Checkpoint**: schema + states + models ready.

---

## Phase 3: User Story 1 — Approved report is delivered to the client (Priority: P1) 🎯 MVP

**Goal**: On approval, render + dispatch to every configured channel via n8n; lifecycle `sent`→`delivered`/`delivery_failed` via authenticated idempotent callback; failure alert + re-send; held paths for no-channel/suspended.

**Independent Test**: Quickstart scenarios A–C (approve→dispatch→callback→delivered; multi-channel failure→resend; held no-channel/suspended→reactivate release).

### Tests for User Story 1

- [x] T011 [P] [US1] Unit test: overall report delivery-status derivation from per-channel `delivery_attempt` rows (delivered=all; failed=any) in `tests/unit/test_delivery_status.py`
- [x] T012 [P] [US1] Unit test: `render_report_document` includes claims+provenance, corroboration count + all sources, narrative; batch = included findings only in `tests/unit/test_delivery_rendering.py`
- [x] T013 [P] [US1] Integration test: approve → dispatch (`sent`, attempt rows, n8n POST mocked) → delivered callback → `delivered` + `delivered_at` + audited; non-approved statuses never dispatch in `tests/integration/test_delivery.py`
- [x] T014 [P] [US1] Integration test: multi-channel one-fails → `delivery_failed` + alert → admin re-send (failed channel only, confirmed channel not re-sent) → `delivered`; callback idempotency + unknown-dispatch 404; no-channel hold; suspended hold → reactivate release in `tests/integration/test_delivery_failure.py`
- [x] T014a [P] [US1] Integration test (FR-007b comprehensive pause): a suspended client is excluded from `query_due_watchlists` (no cycles run) and is included again after reactivation (cycles resume) — asserts the cycle-pause claim, not just delivery hold — in `tests/integration/test_suspension_pause.py`
- [x] T014b [P] [US1] Integration test: dispatch selects the **urgent** recipient for an expedited report and the **regular** recipient otherwise (FR-003) in `tests/integration/test_delivery.py`

### Implementation for User Story 1

- [x] T015 [P] [US1] Implement `render_report_document(report) -> str` (self-contained HTML; no PDF) in `app/delivery/rendering.py`
- [x] T016 [P] [US1] Implement the n8n client — async `httpx` + `tenacity` (3 attempts, never 4xx), POST per channel, mockable — in `app/delivery/n8n_client.py`
- [x] T017 [US1] Implement the delivery service (resolve configured channels per FR-003; dispatch; write/update `delivery_attempt` rows; derive report status; confirm/fail; resend failed-only; hold on no-channel/suspended with fresh-from-stored-state check) in `app/delivery/service.py` (depends T007, T015, T016)
- [x] T018 [US1] Implement durable job `task_deliver_report` (render → dispatch → `sent`/`sent_at`; hold path) — job **body** in `app/delivery/service.py`, the thin ARQ task + DLQ wrapper + registration in `app/jobs/tasks.py` (mirror the spec-11 `enqueue(...)`/dispatcher pattern) (depends T017)
- [x] T019 [US1] Implement + register `on_report_approved` handler (enqueue `task_deliver_report`, `job_id=f"deliver:{report_id}"`) in `app/delivery/handlers.py` and `app/core/lifespan.py` (depends T018)
- [x] T020 [US1] Implement + register `on_client_reactivated` handler (re-enqueue held reports) in `app/delivery/handlers.py` and `app/core/lifespan.py` (depends T018)
- [x] T021 [US1] Implement `POST /clients/{client_id}/reports/{report_id}/delivery-callback` (`X-Delivery-Token` constant-time auth — **bypasses user-JWT auth, service-token only**, consider a slowapi rate limit; idempotent per `(report,channel)`; derive status; 404 unknown dispatch) in `app/delivery/routes.py` (depends T017)
- [x] T022 [US1] Implement `POST /clients/{client_id}/reports/{report_id}/resend` (`require_admin`; failed/unconfirmed channels only) in `app/delivery/routes.py` (depends T017)
- [x] T023 [US1] Raise + audit delivery events (dispatched/delivered/failed/held/resent), scrubbing `error`/`reason` via `app/redaction` (`scrub_text`) in `app/delivery/service.py` (depends T009, T017)
- [x] T024 [US1] Mount the `app/delivery/routes.py` router in the app and confirm RLS context applies to the new client-scoped paths in `app/main.py`

**Checkpoint**: 🎯 MVP — a real approved report reaches the client and resolves to delivered/failed.

---

## Phase 4: User Story 2 — Delivery status visible across reviewer, portal, dashboard (Priority: P2)

**Goal**: Light up the per-report delivery-status display (reviewer), portal sent/delivered, and the dashboard delivery cards.

**Independent Test**: Quickstart scenario E (seeded states render correctly; metrics `delivery` non-null).

### Tests for User Story 2

- [x] T025 [P] [US2] Integration test: reviewer `ReportSummary`/`ReportResponse` carry `delivery_status`; `GET /clients/{id}/metrics` returns non-null `delivery {sent,delivered,failed,success_rate}` in `tests/integration/test_delivery_visibility.py`

### Implementation for User Story 2

- [x] T026 [P] [US2] Add `delivery_status` to reviewer `ReportSummary` + `ReportResponse` and populate it in `app/reports/schemas.py` (+ the list/detail routes in `app/reports/routes.py`)
- [x] T027 [P] [US2] Keep the client-portal set at `{approved, sent, delivered}` — do NOT add `delivery_failed` (a failed delivery means the client never received it; FR-010). `_delivery_status()` may map the `delivery_failed` label defensively, but it must not surface in the portal list — in `app/reports/portal_routes.py`. (Reviewer `delivery_failed` visibility is handled by T026.)
- [x] T028 [P] [US2] Add the `DeliveryMetrics` submodel and change `OpsDashboard.delivery` to `DeliveryMetrics | None` in `app/observability/schemas.py`
- [x] T029 [US2] Populate the delivery block (`sent/delivered/failed/success_rate` = delivered ÷ dispatched) in `app/reports/metrics_routes.py` (depends T028)
- [x] T030 [P] [US2] Update the OpsDashboard zod schema (`delivery` object) + add the field in `frontend/src/api/schemas.ts` and `frontend/src/api/hooks.ts`
- [x] T031 [US2] Render the dashboard Delivery cards from `metrics.delivery` (replace the stub) in `frontend/src/pages/DashboardPage.tsx` (depends T030)
- [x] T032 [P] [US2] Pass `delivery_status` into `DeliveryStatusChip` on the reviewer surfaces in `frontend/src/pages/AllReports.tsx` and `frontend/src/components/ReportDetail.tsx`

**Checkpoint**: delivery state is truthfully visible to all three audiences.

---

## Phase 5: User Story 3 — Reviewer-deadline SLA monitoring + no-callback sweep (Priority: P2)

**Goal**: One periodic sweep — flips stale `sent` reports to `delivery_failed`, and escalates overdue expedited reports in tiers.

**Independent Test**: Quickstart scenario D.

### Tests for User Story 3

- [x] T033 [P] [US3] Integration test: no-callback sweep flips `sent`→`delivery_failed` after the window; Tier-1 (reviewers) then Tier-2 (manager/admin) each fire once; actioned + non-expedited never escalate in `tests/integration/test_sla_sweep.py`

### Implementation for User Story 3

- [x] T034 [US3] Implement the sweep (no-callback timeout flip + tiered SLA escalation; track `sla_escalation_tier`/`sla_escalated_at`; at-most-once per tier) in `app/delivery/sweep.py` (depends T006, T017)
- [x] T035 [US3] Implement escalation + delivery-failure notifications (to the client's reviewers / manager+admin via the n8n client) in `app/delivery/notifications.py` (depends T016)
- [x] T036 [US3] Register the `task_delivery_sla_sweep` cron (default every 15 min) in `worker/worker.py` `_cron_jobs` (depends T034)
- [x] T037 [US3] Raise + audit `SlaEscalated` and the delivery-failure alert through the dispatcher in `app/delivery/sweep.py` (depends T009)

**Checkpoint**: no send sits unconfirmed forever; overdue expedited reports climb the ladder.

---

## Phase 6: User Story 4 — Account-management screens (Priority: P2)

**Goal**: Wire the existing `/staff` and `/clients/{id}/users` backends into two new admin screens.

**Independent Test**: Quickstart scenario G (manager creates a working reviewer + a scoped client-user via the UI).

### Tests for User Story 4

- [x] T038 [P] [US4] Component/integration test: manager creates a reviewer (→ `/queue`) and a scoped client-user (→ `/portal`, in-scope only); non-manager denied the staff screen in `frontend/src/__tests__/accounts.test.tsx`

### Implementation for User Story 4

- [x] T039 [P] [US4] Add API hooks + schemas for `/staff` CRUD and `/clients/{id}/users` CRUD in `frontend/src/api/hooks.ts` and `frontend/src/api/schemas.ts`
- [x] T040 [US4] Build `StaffPage` (list/create/deactivate staff; role select; initial password set by creator) in `frontend/src/pages/StaffPage.tsx` (depends T039)
- [x] T041 [US4] Build `ClientUsersPage` (list/create/deactivate per-client users; scope/min_severity/watchlist; initial password) in `frontend/src/pages/ClientUsersPage.tsx` (depends T039)
- [x] T042 [US4] Add routes (`/staff`, `/clients/:clientId/users`) + role-gated nav entries in `frontend/src/routes.tsx` and `frontend/src/components/AppShell.tsx` (depends T040, T041)

**Checkpoint**: the platform is operable without scripted accounts.

---

## Phase 7: User Story 5 — Report download + audit export (Priority: P3)

**Goal**: Enable the two disabled buttons; add the report-download + audit-export endpoints with correct authorization.

**Independent Test**: Quickstart scenario F.

### Tests for User Story 5

- [x] T043 [P] [US5] Integration test: report download — owning client-user 200, other client 404, staff acting-client in `tests/integration/test_report_download.py`
- [x] T044 [P] [US5] Integration test: audit access/export role model — manager all events, admin client/watchlist only, reviewer 403; `AuditExported` audited in `tests/integration/test_audit_export.py`

### Implementation for User Story 5

- [x] T045 [US5] Implement `GET /clients/{client_id}/reports/{report_id}/download` (reuse `render_report_document`; client-user own approved/sent/delivered only; staff acting-client) in `app/delivery/routes.py` (depends T015)
- [x] T046 [US5] Refine `GET /audit` authorization — admin → client/watchlist categories only; reviewer → 403 — in `app/audit/routes.py`
- [x] T047 [US5] Implement `GET /audit/export?format=csv|json` (manager/admin; bounded/paginated; emits `AuditExported`) in `app/audit/routes.py` (depends T046, T009)
- [x] T048 [P] [US5] Enable + wire `DownloadReportButton` to the download endpoint in `frontend/src/components/DownloadReportButton.tsx`
- [x] T049 [P] [US5] Enable + wire `AuditExportButton` to `/audit/export` in `frontend/src/components/admin/AuditExportButton.tsx`

**Checkpoint**: downloadable reports + exportable audit trail, correctly scoped.

---

## Phase 8: User Story 6 — Budget-threshold notification (Priority: P3)

**Goal**: Wire the spec-11 budget event to a real outbound agency notification.

**Independent Test**: Quickstart scenario H (warning/exceeded crossing → one notification per state).

### Tests for User Story 6

- [x] T050 [P] [US6] Integration test: budget warning/exceeded crossing → notification to manager+admin, audited, not re-sent while in the same state in `tests/integration/test_budget_notify.py`

### Implementation for User Story 6

- [x] T051 [US6] Implement + register the `WatchlistBudgetThresholdReached` handler (notify the client's manager+admin via the n8n client; dedup by state) in `app/delivery/notifications.py` and `app/core/lifespan.py` (depends T035)

**Checkpoint**: the agency is proactively nudged at budget thresholds.

---

## Phase 9: User Story 7 — Close out residual stubbed controls (Priority: P3)

**Goal**: Dead-letter card; verify budget-policy control; manual-consolidate 202 handling.

**Independent Test**: Quickstart scenario H (dead-letter card count; consolidate 202 ack).

### Implementation for User Story 7

- [x] T052 [US7] Build `DeadLetterCard` (reads `GET /admin/dead-letters` / `failed_jobs`) and mount it on the admin dashboard in `frontend/src/components/admin/DeadLetterCard.tsx` (+ `frontend/src/pages/DashboardPage.tsx`) — NOT `[P]`: shares `DashboardPage.tsx` with T031, sequence after it
- [x] T053 [P] [US7] Verify the budget-exceeded-policy control persists (already built at `frontend/src/components/admin/WatchlistEditor.tsx:170-184`) and add a regression test if missing — verify-only, no new control
- [x] T054 [US7] **First locate** the manual consolidate-batch control (grep the SPA for the consolidate-batch call; `TriggerButton.tsx` handles *ingest*, not consolidate), then adjust whichever component triggers consolidate to handle the 202 enqueue (acknowledge + refresh/poll, no inline report) in `frontend/src/components/admin/` — confirm the file before editing

**Checkpoint**: no stubbed control left dangling.

---

## Phase 10: User Story 8 — Complete LangSmith tracing wiring (Priority: P3)

**Goal**: Worker configures tracing like the API; deployment passes the env through; stays OFF by default.

**Independent Test**: Quickstart scenario I.

### Tests for User Story 8

- [x] T055 [P] [US8] Unit test: `configure_tracing` sets the three `LANGCHAIN_*` env vars when enabled+key, no-op when disabled or empty; `monkeypatch` restores env in `tests/unit/test_tracing_config.py`

### Implementation for User Story 8

- [x] T056 [US8] Add `configure_tracing(settings)` to worker startup immediately after `ctx["settings"] = settings` (mirror `app/core/lifespan.py:64`) in `worker/worker.py`
- [x] T057 [P] [US8] Add `TRACING_ENABLED: ${TRACING_ENABLED:-false}` / `LANGSMITH_API_KEY: ${LANGSMITH_API_KEY:-}` / `LANGSMITH_PROJECT: ${LANGSMITH_PROJECT:-pantera}` to BOTH `api` and `worker` services in `docker-compose.yml` (default OFF; flag must be `false`, never empty)

**Checkpoint**: flipping the switch traces the real worker pipeline, PII-free.

---

## Phase 11: Polish & Cross-Cutting Concerns

- [x] T058 [P] Update runbook/security docs (delivery + SLA flow, callback auth, n8n config) in `docs/`
- [x] T059 [P] Add/verify a redaction-gate assertion that delivery + notification **logs/traces** carry no fake PII/secret (scope to log + trace values ONLY — the rendered report body delivered to its own client is intentionally NOT redacted) in `tests/integration/` (or extend the existing redaction test)
- [x] T060 Run `uv run ruff check app worker tests` AND `uv run black --check app worker tests`; fix all
- [x] T061 Run the full suite (`uv run pytest` + `PANTERA_INTEGRATION=1 uv run pytest tests/integration`); confirm ≥80% overall and ≥95% on delivery DB-write/callback/HITL-adjacent paths
- [x] T062 Execute `specs/013-delivery/quickstart.md` scenarios A–I against real services (n8n mocked); fix gaps
- [x] T063 Fresh-clone smoke: `docker compose up` + build/serve the SPA incl. the new Staff/Users screens
- [x] T064 Cross-check every "does-not-exist-yet" item in `implementation-notes.md` is built; move the resolved spec-13 items to "Resolved" in the frontend-forward-dependency ledger (memory)

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (P1)** → no deps.
- **Foundational (P2)** → after Setup; **BLOCKS US1/US2/US3** (schema, states, models, events).
- **US1 (P3 phase)** → after Foundational. **MVP.**
- **US2** → after Foundational; meaningful data needs US1 (testable with seeded states).
- **US3** → after Foundational; the no-callback sweep operates on US1's `sent` state (build after/with US1).
- **US4, US8** → after Setup only (independent of delivery) — can run anytime in parallel.
- **US5** → download depends on US1's `render_report_document` (T015); audit export is independent.
- **US6** → depends on the notification client from US3 (T035).
- **US7** → independent (frontend + existing backends).
- **Polish (P11)** → after all desired stories.

### Within each story

Tests → models → services → endpoints/jobs → integration → UI. Models before services; services before endpoints.

### Parallel opportunities

- Setup: T001/T002/T003 all [P].
- Foundational: T006/T007/T008/T009 [P] after T004; T005 (migration) then T010 (apply).
- US1 tests T011–T014 [P]; impl T015/T016 [P] then T017→T018→T019/T020/T021/T022.
- Independent stories US4 + US8 can proceed alongside US1 once Setup is done.

---

## Parallel Example: User Story 1

```bash
# Tests first (all [P]):
Task: "Unit: delivery-status derivation — tests/unit/test_delivery_status.py"
Task: "Unit: report rendering — tests/unit/test_delivery_rendering.py"
Task: "Integration: approve→dispatch→callback→delivered — tests/integration/test_delivery.py"
Task: "Integration: failure+resend+held paths — tests/integration/test_delivery_failure.py"

# Then parallel leaf implementations:
Task: "render_report_document — app/delivery/rendering.py"
Task: "n8n client — app/delivery/n8n_client.py"
```

---

## Implementation Strategy

### MVP first (US1 only)

1. Phase 1 Setup → 2. Phase 2 Foundational (CRITICAL) → 3. Phase 3 US1 → **STOP & VALIDATE** (quickstart A–C; a real report reaches the client) → demo.

### Incremental delivery

Foundation → US1 (MVP) → US2 (visibility) → US3 (SLA) → US4 (accounts) → US5 (export) → US6 (budget notify) → US7 (residual) → US8 (tracing) → Polish. Each story is an independently testable increment.

### Notes

- [P] = different files, no incomplete deps. [Story] label = traceability.
- Commit after each task/logical group (Conventional Commits, **no Co-Authored-By**; PRs < 400 lines).
- Verify tests fail before implementing where practical.
- **Do-not-rebuild reminders** (implementation-notes §1): `DeliveryStatusChip`, the budget-policy control (T053 verify-only), `GET /audit`, the durable `enqueue` + cron patterns, `configure_tracing`/`traced_llm_call`, and the redaction API all already exist.
