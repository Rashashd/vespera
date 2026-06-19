# Phase 0 Research — Report Delivery & Final Wiring

Each decision is grounded in the live codebase (see [implementation-notes.md](./implementation-notes.md) for file:line anchors). Format: Decision · Rationale · Alternatives rejected.

## D1. Delivery trigger = `ReportApproved` domain event → durable ARQ job

- **Decision**: Register a passive handler `on_report_approved` on the existing dispatcher; it enqueues a durable ARQ job `task_deliver_report` (deterministic `job_id=f"deliver:{report_id}"`). The job renders the document, resolves configured channels, POSTs each to n8n, sets `sent`/`sent_at`, and writes per-channel `delivery_attempt` rows + an audited `ReportDispatched` event.
- **Rationale**: `app/reports/review.py:53` already dispatches `ReportApproved` (no consumer beyond audit). Mirrors spec-11 durability (every trigger is an enqueue, FR-001/G1). Keeps drafting/sending separate (Constitution I) — approval authorizes; the job sends. Idempotent `job_id` prevents double-dispatch.
- **Alternatives rejected**: (a) Send inline in the approve route — blocks the request, not durable, couples drafting to sending. (b) A new poller — redundant with the event bus.

## D2. Delivery lifecycle + per-channel tracking

- **Decision**: Add `sent`, `delivered`, `delivery_failed` to `ReportStatus`; widen the `reports.status` CHECK (migration 0012). A new `delivery_attempt` table holds one row per `(report_id, channel)` with `status` (`pending`/`delivered`/`failed`), `error`, and timestamps. The report's overall status is **derived**: `delivered` only when every configured channel's attempt is `delivered`; `delivery_failed` if any attempt is `failed` after retries. Record `delivered_at` on the report when all confirm.
- **Rationale**: Honors the clarified all-channels-confirm rule (FR-004/004a) and enables per-channel re-send (FR-006). Mirrors the existing `ReportFollowup.status IN ('generated','sent','failed')` precedent (`app/reports/models.py:129`).
- **Alternatives rejected**: Single status flag on `reports` — can't represent partial multi-channel outcomes or targeted re-send.

## D3. n8n integration + callback

- **Decision**: `app/delivery/n8n_client.py` POSTs to the n8n webhook (URL from Vault/Settings) per channel, with the rendered document + target + a callback reference. n8n delivers and calls back `POST /clients/{client_id}/reports/{report_id}/delivery-callback` with `{channel, outcome, delivered_at?, error?}`. The callback is authenticated by a shared service token header (`X-Delivery-Token`, constant-time compare) — mirroring the existing modelserver/guardrails `X-Service-Token` pattern — and is **idempotent**, keyed on `(report_id, channel)`: a duplicate/late/out-of-order callback never changes an already-final attempt; an unknown dispatch is rejected (404).
- **Rationale**: n8n is the constitution-sanctioned notification/SFTP layer (no new broker, FR-023). Shared-token auth matches the project's service-to-service pattern and is testable. Per-(report,channel) idempotency closes CHK022.
- **Alternatives rejected**: (a) HMAC-signed body — more moving parts than the established service-token pattern; revisit only if n8n can't set a static header. (b) Polling n8n for status — n8n is push-oriented; a callback is simpler. (c) No callback (treat dispatch as delivered) — rejected at clarify (Q1 → option B keeps `delivered` callback-confirmed).

## D4. No-callback timeout + SLA monitor = one periodic sweep cron

- **Decision**: One new ARQ cron `task_delivery_sla_sweep` (default every 15 min; added to `worker/worker.py` `_cron_jobs`). It (a) flips any report `sent` longer than the no-callback window (**default 6h**, configurable) to `delivery_failed` + staff alert (FR-006a); and (b) escalates open expedited reports past `sla_deadline` in **tiers** — Tier-1 → the client's reviewers, Tier-2 → manager/admin after a further interval (**default 2h**) — tracked by `reports.sla_escalation_tier` + `sla_escalated_at` so each tier fires at most once (FR-012/013).
- **Rationale**: Reuses the spec-11 cron registration pattern (`worker/worker.py` `_arq_cron(...)`). One sweep covers both time-based concerns. "Assigned reviewer" was corrected at readiness to "the client's reviewers" (shared queue — there is no per-report assignee).
- **Alternatives rejected**: Two separate crons — unnecessary; both are cheap time scans over the same report set. Per-report timers — not durable/restart-safe.

## D5. Suspension cascade = leverage the existing client-status gate (SIMPLIFIED at plan time)

- **Decision**: Do **not** flip `watchlist.is_active` on suspension and do **not** track "paused" watchlists. `CycleService.query_due_watchlists()` already filters `Client.status == "active"` (`app/scheduling/service.py:181-182`), so a suspended client runs no cycles today. Spec 13 adds only: the delivery job/handler **holds** delivery when `client.status != "active"` (report stays approved-pending-delivery + alert), and reactivation **releases** held reports (re-enqueue) — cycles resume automatically. Audited via `ClientSuspended`/`ClientReactivated` (already raised).
- **Rationale**: The grounding showed the "comprehensive pause" the user wanted is already true for cycles; flipping `is_active` would add reactivation-restore bookkeeping for no behavioral gain and would conflate suspension with explicit staff deactivation. Simpler + correct. (Spec FR-007b, the suspension clarification, edge case, and assumptions were aligned to this.)
- **Alternatives rejected**: Flip `is_active` + track which were suspension-paused so reactivation restores only those — extra schema + logic, no behavioral benefit since cycles already gate on client status.

## D6. Report rendering = HTML now; PDF a drop-in later

- **Decision**: `render_report_document(report) -> str` builds a self-contained HTML document carrying the report's structured claims + provenance, corroboration count + all sources, and narrative (batch = included findings only). One render feeds the email body/attachment, the SFTP file, and the report download (FR-002/017). No PDF dependency.
- **Rationale**: PDF (and MinIO storage) are explicit future improvements (brief §9); HTML→PDF is a thin later add. Avoids bloating any image (Principle VI). Single source of truth for the delivered artifact and the download.
- **Alternatives rejected**: Generate PDF now (WeasyPrint/headless browser) — native-lib/browser bloat against the lean-container rule; deferred per clarify.

## D7. Per-client SFTP credentials live in n8n, not the app DB

- **Decision**: `clients` gains SFTP **destination metadata** only (`sftp_enabled`, `sftp_host`, `sftp_path`, `sftp_username`). The SFTP **credential** (password/key) lives in n8n's native credential store, keyed per client (brief §9: "n8n native SFTP node; no backend code change"). Email recipients reuse the existing `report_email_regular`/`report_email_urgent` columns.
- **Rationale**: Keeps secrets out of the app DB (FR-025); matches the brief's n8n-native SFTP intent; the app only needs to know a channel is configured + where to route.
- **Alternatives rejected**: Store SFTP secrets in Vault keyed by client and pass to n8n — viable but duplicates n8n's credential management; revisit only if n8n credential-per-client proves impractical.

## D8. Budget-threshold notification (US6)

- **Decision**: Register a passive handler on the existing `WatchlistBudgetThresholdReached` event (`app/scheduling/budget_policy.py:45`) that sends an n8n notification to the client's **manager + admin**. Dedup is inherent — the event fires only on a state *crossing*; the handler does not re-notify while the watchlist stays in the same budget state.
- **Rationale**: Spec 11 already records the crossing as a domain event (deferred only the active send). This is a thin passive handler, like the audit handler.
- **Alternatives rejected**: A separate budget poller — redundant with the event.

## D9. Audit export + role refinement (US5)

- **Decision**: `GET /audit` (`app/audit/routes.py:26`) exists and is staff-only with category filters. Refine authorization: **manager** = all events; **admin** = only client/watchlist-management categories; **reviewer** = 403; client-users never. Add `GET /audit/export?format=csv|json` (manager/admin, bounded/paginated) that streams the filtered log and emits an audited `AuditExported` event.
- **Rationale**: Reuses the existing query/endpoint; adds the missing export + the clarified role-based event-category visibility (FR-018). `audit_log` is RLS-exempt (migration 0011) so cross-client manager export works; it is the audited internal-operator exception (Constitution V).
- **Alternatives rejected**: A brand-new audit service/view — the view already exists.

## D10. LangSmith tracing wiring (US8)

- **Decision**: Add `configure_tracing(settings)` to `worker/worker.py` startup immediately after `ctx["settings"] = settings` (mirrors `app/core/lifespan.py:64`). Add `TRACING_ENABLED` (default `false`, never empty), `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` passthrough to the `api` + `worker` services in `docker-compose.yml`. Add a fast unit test for `configure_tracing` (enabled+key sets the three `LANGCHAIN_*` vars; disabled/empty = no-op; `monkeypatch` restores env). Tracing stays **OFF by default**.
- **Rationale**: Triage + drafting LLM calls run in the worker, which never configures tracing today (the real gap). Everything else exists (helper, decorator, config fields, API wiring, triage decoration, `langsmith` dep). Key stays env-driven (decided), not a required secret.
- **Alternatives rejected**: Add the key to `_REQUIRED_SECRETS` — would break boot when empty; tracing is optional/observability-only.

## D11. Frontend light-ups (US2/US5/US7) + new screens (US4)

- **Decision**: `DeliveryStatusChip` already renders all four states and is mounted in `AllReports`/`ReportDetail`/portal — it lights up once the reviewer `ReportSummary`/`ReportResponse` schemas carry `delivery_status` (portal already does). Populate the dashboard Delivery section from `metrics.delivery`. Enable `DownloadReportButton` + `AuditExportButton` by wiring the new endpoints. Add a `DeadLetterCard` (data already at `GET /admin/dead-letters` + `failed_jobs` on metrics). Build two new pages — `StaffPage` (wire `/staff`) and `ClientUsersPage` (wire `/clients/{id}/users`) — with nav entries.
- **Rationale**: The grounding confirmed components are built/disabled and endpoints mostly exist; this is wiring, not redesign. **FR-020 (budget-policy control) is already implemented** (`WatchlistEditor.tsx:170-184`) → verify-only.
- **Alternatives rejected**: Rebuild components — wasteful; they were stubbed intentionally.

## D12. Manual consolidate-batch 202 handling (US7, FR-022)

- **Decision**: Verify the admin manual-consolidate control handles the spec-11 **202 enqueue** (acknowledge + refresh/poll) rather than expecting an inline report. The grounded `TriggerButton` handles ingest with a simple toast; confirm the consolidate trigger path and adjust it to the 202 pattern if it still expects a synchronous body.
- **Rationale**: Spec 11 converted consolidate-batch to 202; the UI must not block on an inline report (ledger item).
- **Alternatives rejected**: n/a (verification + small adjustment).

## Migration plan

One migration **`0012_delivery.py`** (`down_revision="0011"`): widen `reports.status` CHECK; add `reports` delivery + SLA-escalation columns; add `clients` SFTP destination columns; create `delivery_attempt` (client-scoped) **with an RLS policy** matching the migration-0011 pattern. See [data-model.md](./data-model.md).

## Testing strategy

- **Unit**: `configure_tracing` on/off; overall-status derivation from per-channel attempts; HTML rendering content; sweep tier logic + no-callback flip; callback idempotency.
- **Integration** (`PANTERA_INTEGRATION=1`, n8n mocked): approve → dispatch (`sent`) → callback → `delivered` (+`delivered_at`); channel failure → `delivery_failed` + alert → re-send → `delivered`; suspended client → held → reactivate → released; SLA Tier-1 then Tier-2; audit export authz (manager all / admin client-watchlist-only / reviewer 403); account-mgmt create reviewer + client-user.
- **Gates**: ≥80% overall, 95% on delivery DB-writes + the callback/HITL-adjacent paths; redaction gate stays green (delivery/notification logs PII-free); fresh-clone smoke builds/serves the SPA with the new screens.
