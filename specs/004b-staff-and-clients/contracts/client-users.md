# Contract: Client-Side User Management (admin, per named client)

**Feature**: 004b-staff-and-clients · `app/clients/routes_client_users.py` · guard `require_admin`
(admin or manager) + `acting_client`. Schema + scope stored **now**; client-user login + report-
visibility enforcement deferred to the report spec (FR-016). All writes audited (FR-021).

## POST `/clients/{client_id}/users` — create a client-side user

- Auth: `require_admin` + `acting_client` (client must exist & be active).
- Body: `{ email, password, client_scope, min_severity?, watchlist_ids? }`
  - `client_scope` REQUIRED (`full` | `scoped`) — explicit choice, no silent default (FR-014).
  - If `scoped`: at least one of `min_severity` (a `SeverityLevel`) or non-empty `watchlist_ids`
    (else 400 `SCOPE_REQUIRED`).
  - `user_type` is forced to `client`, `client_id` from the path — never the body (FR-009).
  - Each `watchlist_id` MUST belong to `{client_id}` (else 400 `CROSS_CLIENT_WATCHLIST`, FR-014).
- 201 → `ClientUserOut { id, email, client_id, role='client_user', client_scope, min_severity,
  watchlist_ids, is_active }`.
- Errors: 403 reviewer/client-user; 409 `USER_ALREADY_EXISTS`; 400 `PASSWORD_POLICY`/`INVALID_EMAIL`/
  `SCOPE_REQUIRED`/`CROSS_CLIENT_WATCHLIST`. Audit: `ClientUserCreated`.

## GET `/clients/{client_id}/users` — list a client's users

- Auth: `require_admin` + `acting_client`. 200 → `list[ClientUserOut]`.

## PATCH `/clients/{client_id}/users/{user_id}` — update scope / active

- Auth: `require_admin` + `acting_client`. Body: `{ client_scope?, min_severity?, watchlist_ids?,
  is_active? }`. Same scope rules as create; cross-client watchlist refused; an empty/absent scope is
  **no visibility** (default-deny), never widened to full. Client-users can never set their own scope
  (FR-015). `user_type`/`client_id` immutable (400 `IMMUTABLE_FIELD`).
- 200 → `ClientUserOut`. Audit: `ClientUserScopeChanged` (and/or `UserDeactivated`).

## Scope semantics (recap, FR-014/D4)

| client_scope | min_severity | watchlist_ids | Visible (when enforced later) |
|--------------|--------------|---------------|-------------------------------|
| `full` | — | — | all of this client's reports |
| `scoped` | set | — | reports ≥ severity, all watchlists |
| `scoped` | — | set | reports in those watchlists, any severity |
| `scoped` | set | set | reports in those watchlists AND ≥ severity |
| absent/empty | — | — | **nothing** (default-deny; creation refused) |

Scope links survive a watchlist **soft-deactivation**; only a hard-delete cascades them (CASCADE FK).
