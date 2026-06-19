# API Contracts — Report Delivery & Final Wiring

New and changed HTTP surfaces. All client-scoped routes go under the existing `/clients/{client_id}/...` prefix and use `acting_client()` + the role guards already in the codebase. Bodies are Pydantic; routes never return ORM objects.

## 1. Delivery confirmation callback (NEW) — n8n → backend

```
POST /clients/{client_id}/reports/{report_id}/delivery-callback
Auth: X-Delivery-Token: <shared service token>   (constant-time compare; 401 on mismatch)
Body: { "channel": "email" | "sftp", "outcome": "delivered" | "failed",
        "delivered_at": "<iso8601>"?, "error": "<short, PII-free>"? }
```

- **200** `{ "report_status": "sent"|"delivered"|"delivery_failed" }` — updates the matching `delivery_attempt (report_id, channel)`; recomputes overall report status (delivered only when all configured channels confirmed).
- **Idempotent**: a duplicate/late/out-of-order callback that targets an already-final attempt is a no-op `200` (does not flip a delivered attempt).
- **404** if `(report_id, channel)` has no dispatched attempt for this client (unknown dispatch rejected).
- **401** if the token is missing/wrong. Never reveals report content.

## 2. Staff re-send (NEW)

```
POST /clients/{client_id}/reports/{report_id}/resend
Auth: require_admin (admin/manager) — NOT reviewer
```

- Re-dispatches only the **unconfirmed/failed** channels (never a confirmed one); transitions the report back to `sent`. Used for `delivery_failed` reports and for releasing a report held by a previously-missing channel.
- **200** `ReportSummary` (with the updated delivery status). **409** if nothing to re-send (already fully delivered). Audited (`ReportResent`).

## 3. Report download (ENABLE — FR-017)

```
GET /clients/{client_id}/reports/{report_id}/download
Auth: client-user → only OWN approved/sent/delivered reports; staff → acting client
```

- **200** the rendered report document (the same artifact delivered; `Content-Type: text/html`, `Content-Disposition: attachment`).
- **404** if not entitled or not yet approved/sent/delivered. Lights up `DownloadReportButton`.

## 4. Audit export + role refinement (US5 / FR-018)

```
GET /audit                      (existing — refine authorization)
GET /audit/export?format=csv|json&category=&client_id=&from=&to=&limit=
Auth: manager → ALL events; admin → ONLY client/watchlist-management categories; reviewer → 403; client-users → 403
```

- `GET /audit` already returns newest-first with category/event_type/client_id filters (`app/audit/routes.py:26`). **Change**: enforce the role-based event-category visibility above (admin restricted to the client/watchlist categories; reviewer denied).
- `GET /audit/export` streams the filtered append-only log as CSV or JSON (bounded/paginated). The export itself is audited (`AuditExported`). Lights up `AuditExportButton`.

## 5. Manager metrics — delivery block (POPULATE — FR-011)

```
GET /clients/{client_id}/metrics   (existing — app/reports/metrics_routes.py)
```

- `OpsDashboard.delivery` changes from `null` to `DeliveryMetrics { sent, delivered, failed, success_rate }` (success_rate = delivered ÷ dispatched in window). No new route; fills the documented spec-13 gap.

## 6. Account management (WIRE EXISTING — US4)

No new endpoints — the SPA wires what exists:

```
POST   /staff                              (require_manager)   body: {email, password, role}      app/auth/routes_staff.py:19
GET    /staff                              (require_manager)   list                               app/auth/routes_staff.py:69
PATCH  /staff/{user_id}                     (require_manager)   {role?, is_active?}  (last-manager guard)  :89
POST   /clients/{client_id}/users           (require_admin)     {email, password, client_scope, min_severity, watchlist_ids}  routes_client_users.py:23
GET    /clients/{client_id}/users           (require_admin)     list                               :90
PATCH  /clients/{client_id}/users/{user_id}  (require_admin)     {client_scope?, min_severity?, watchlist_ids?, is_active?}  :102
```

- Initial credential: the creator supplies `password` on create (hashed server-side); communicated out-of-band (FR-016a). No invite-email/self-service reset (future).

## 7. SFTP destination on client config (extend existing client config write)

- The per-client config write path (the existing report-emails/config endpoints under `/clients/{client_id}/...`) accepts the new SFTP destination fields (`sftp_enabled`, `sftp_host`, `sftp_path`, `sftp_username`). The SFTP **credential** is managed in n8n, not sent here (D7).

## n8n outbound contract (backend → n8n)

```
POST <n8n_webhook_url>                      (from Vault/Settings; httpx + tenacity, 3 attempts, no 4xx retry)
Body: { report_id, client_id, channel, recipient (email) | sftp_ref (client),
        document (rendered HTML), callback_url, callback_token }
```

- n8n performs the email send / SFTP put (credentials from its own store), then calls back endpoint #1. In CI/tests this POST is **mocked**; the callback endpoint is exercised directly.

## Notifications (backend → n8n, internal-staff alerts)

- Delivery-failure alert, SLA Tier-1/Tier-2 escalation, and budget-threshold notification are routed via the same n8n notification path to internal staff (manager/admin; Tier-1 → the client's reviewers). No client-facing endpoint. Each is audited.
