# Report Delivery & Notifications — Runbook (spec 13)

Operational reference for the report-delivery lifecycle, the n8n routing layer, the SLA sweep, and
staff notifications. Schema: migration `0012`; code: `app/delivery/`.

## Lifecycle

```
approved ──deliver job──▶ sent ──all channels confirm──▶ delivered      (terminal)
   │  (no channel / suspended → held; stays approved + alert)  │
   │                                              any channel fails / no callback in window
   └◀── reactivate / staff resend ───────────── delivery_failed ──resend──▶ sent
```

- On reviewer **approval**, the `ReportApproved` handler enqueues the durable `task_deliver_report`
  (`job_id=deliver:{report_id}`). The job re-checks the report is still `approved` at send time (HITL
  gate), renders a self-contained HTML document, and dispatches to **every configured channel**.
- **Configured channels** (FR-003): email = a non-null recipient for the report's urgency
  (expedited → `report_email_urgent`, batch → `report_email_regular`); SFTP = `sftp_enabled` with
  `sftp_host` + `sftp_path`. The SFTP **credential lives in n8n**, never in the app DB — the app stores
  destination metadata only.
- Overall report status is **derived** from `delivery_attempt` rows: delivered = all delivered;
  delivery_failed = any failed; otherwise sent.
- **Held** paths (report stays `approved`, staff alerted): no configured channel, or the client is
  suspended. Reactivating the client re-enqueues delivery; staff `resend` also releases a held report.

## n8n integration

- Backend → n8n: `POST {N8N_WEBHOOK_URL}` per channel with `{report_id, client_id, channel, document,
  recipient|sftp_ref, callback_url, callback_token}` (httpx + tenacity, 3 attempts, never retries 4xx).
- n8n → backend callback: `POST /clients/{id}/reports/{rid}/delivery-callback` with header
  `X-Delivery-Token: {DELIVERY_CALLBACK_TOKEN}` (constant-time compare). Body
  `{channel, outcome: delivered|failed, delivered_at?, error?}`. Idempotent per `(report, channel)`;
  unknown dispatch → 404; missing/wrong/unset token → 401.
- Config (Vault secrets, OPTIONAL — app boots and **holds** delivery when unset; NOT in
  `_REQUIRED_SECRETS`): `n8n_webhook_url`, `delivery_callback_token`.

## SLA sweep (cron, every `delivery_sweep_interval_minutes`, default 15)

`task_delivery_sla_sweep` → `app/delivery/sweep.py`:
- **No-callback timeout**: a `sent` report whose `sent_at` predates `delivery_no_callback_window_hours`
  (default 6) → `delivery_failed` + staff alert.
- **Tiered reviewer-deadline SLA**: an open expedited report past `sla_deadline` escalates Tier-1
  (the client's reviewers); after `sla_tier2_interval_hours` (default 2) still un-actioned → Tier-2
  (manager/admin). Each tier fires at most once; an actioned report never escalates.

## Notifications (internal staff, via n8n)

Delivery-failure, SLA Tier-1/Tier-2, and budget-threshold alerts route through the same n8n path to
staff (`app/delivery/notifications.py`). Payloads carry **ids/codes/recipient emails only** — never
document text or PII; `error`/`reason` are scrubbed via `app/redaction` before logging/persistence.
Budget-threshold notifications dedup by state (one alert per crossing, no storm).

## Security notes

- Delivery/notification **logs and traces are PII-free** (Presidio/`scrub_text`). The **rendered report
  body delivered to its own client is the intended deliverable and is NOT redacted**.
- The callback path bypasses user-JWT auth (service-token only) and sets per-client RLS context
  explicitly. All other delivery routes use `acting_client` + role guards.
- Report **download** (`GET /reports/{id}/download`): client-users get only their own approved/sent/
  delivered reports; staff get the acting client. **Audit export** (`GET /audit/export`): manager → all
  events; admin → client/watchlist-management only; reviewer → 403. The export is itself audited.

## LangSmith tracing (US8)

OFF by default. Both API and worker call `configure_tracing(settings)`; tracing activates only when
`TRACING_ENABLED=true` AND a `LANGSMITH_API_KEY` is set. Agent messages are Presidio-redacted at egress,
so traces carry only redacted content (redaction is the control).
