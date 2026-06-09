# Contract: Authorization Model (user_type × role, acting-client, freshness)

**Feature**: 004b-staff-and-clients · internal authorization contract consumed by every route here.

## Principals

| user_type | role | client_id | Cross-client? | Notes |
|-----------|------|-----------|---------------|-------|
| staff | manager | NULL | yes (all) | superuser: client lifecycle + all staff accounts |
| staff | admin | NULL | yes (all) | client-user mgmt, report emails, ingestion triggers |
| staff | reviewer | NULL | yes (read) | report approve/reject/edit permission (later spec) |
| client | client_user | set | no (own only) | severity/watchlist-scoped; login+enforcement deferred |

## Guards (`app/auth/dependencies.py`)

- `current_active_principal` — authenticated active user, **re-read from DB each request**; for
  `client_user`, also 401/403 if their client `status != 'active'` (freshness, FR-019).
- `require_staff` — any staff role; 403 for client-users; 401 if unauthenticated.
- `require_manager` — `role='manager'` only.
- `require_admin` — `role ∈ {manager, admin}` (manager inherits admin powers, FR-003).
- `require_reviewer_or_admin` — read/permission paths.
- `acting_client(client_id: path)` — loads client; 404 if missing or (for client-users) not their own;
  400 `CLIENT_SUSPENDED` for new-work routes when `status='suspended'`. Returns the validated client and
  is the value recorded as `target_client_id` in audit.

## Rules (normative)

1. `user_type` and `client_id` are **never** read from a request body; derived/validated server-side
   (FR-009). Mutating them post-creation is manager-only and audited.
2. Only a manager may create a user with `role='manager'` or promote anyone to manager (FR-004).
3. The last active manager cannot be demoted/deactivated, including self-action (FR-005).
4. Every client-scoped staff action carries a `{client_id}` path param validated by `acting_client`;
   no implicit "all clients" (FR-008). Roster `GET /clients` is staff-readable; mutation manager-only.
5. Authorization is computed from current stored state, not token claims; access token ~8h, expiry ⇒
   re-login (FR-019). Errors: 401 unauthenticated, 403 forbidden (wrong role/type), 404 cross-tenant
   (no existence leak), 400 validation/`CLIENT_SUSPENDED`.

## Error vocabulary

`FORBIDDEN`, `NOT_AUTHENTICATED`, `CLIENT_NOT_FOUND`, `CLIENT_SUSPENDED`, `USER_NOT_FOUND`,
`USER_ALREADY_EXISTS`, `LAST_MANAGER`, `MANAGER_REQUIRED`, `IMMUTABLE_FIELD`, `CROSS_CLIENT_WATCHLIST`,
`SCOPE_REQUIRED`, `PASSWORD_POLICY`, `INVALID_EMAIL`.
