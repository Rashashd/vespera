# Contract: Client Lifecycle & Report Delivery

**Feature**: 004b-staff-and-clients · `app/clients/routes_clients.py`. Lifecycle = manager-only;
report-email config = admin (incl. manager). Roster read = any staff. All writes audited (FR-021).

## GET `/clients` — list the client roster

- Auth: `require_staff` (any staff role). 200 → `list[ClientOut]` (so staff can pick a target client,
  FR-008). Not available to client-users.

## GET `/clients/{client_id}` — client detail

- Auth: `require_staff` (any). 200 → `ClientOut { id, name, status, report_email_regular,
  report_email_urgent, urgent_severity_threshold, created_at }`. 404 `CLIENT_NOT_FOUND`.

## POST `/clients` — create a client (replaces seed script)

- Auth: `require_manager`. Body: `{ name, report_email_regular?, report_email_urgent?,
  urgent_severity_threshold? }`. `status` defaults `active`; threshold defaults `life-threatening`.
- 201 → `ClientOut`. Errors: 403 non-manager; 409 duplicate name (existing case-insensitive unique);
  400 `INVALID_EMAIL`. Audit: `ClientCreated`.

## POST `/clients/{client_id}/suspend` — soft-delete (freeze)

- Auth: `require_manager`. Sets `status='suspended'`: no new ingestion runs accepted, client-user
  logins blocked (via freshness check), **all data preserved**, reactivatable (FR-011). Idempotent.
- 200 → `ClientOut`. Audit: `ClientSuspended`. (No hard-delete endpoint exists — FR-012.)

## POST `/clients/{client_id}/reactivate` — restore

- Auth: `require_manager`. Sets `status='active'`; new work + client-user login resume (FR-011).
- 200 → `ClientOut`. Audit: `ClientReactivated`.

## PATCH `/clients/{client_id}/report-emails` — set delivery addresses

- Auth: `require_admin` (admin or manager). Body: `{ report_email_regular?, report_email_urgent?,
  urgent_severity_threshold? }` — single address each (`EmailStr`); malformed refused, stored values
  unchanged (FR-017). Storage only; sending is a later spec (urgent/emergency = delivered immediately,
  recorded for the notification spec, FR-018).
- 200 → `ClientOut`. Errors: 400 `INVALID_EMAIL`; 403 reviewer/client-user. Audit:
  `ClientReportEmailChanged` with `changes`.

## Edge

- Suspending a client while one of its ingestion runs is mid-execution: the in-flight run finishes and
  records its result; no new run accepted afterward (consistent with spec-4 FR-024).
