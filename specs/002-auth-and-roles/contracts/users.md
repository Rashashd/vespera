# API Contract: Admin User Management

Base path: `/users`. **All endpoints require an authenticated `admin` (`require_admin` → 401 if
unauthenticated, 403 if not admin).** All operations are scoped to the acting admin's own
`client_id` (FR-007, Constitution V) — users of other clients are invisible (404, never reveal
existence). Custom router (research D9). Mutations emit audit events.

## Schemas

**UserRead** (response; never includes any password field):
```json
{ "id": 12, "email": "a@x.com", "role": "reviewer", "is_active": true,
  "client_id": 3, "created_at": "2026-06-06T10:00:00Z" }
```

**UserCreate** (request):
| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `email` | string (email) | yes | Globally unique; normalized lowercase |
| `password` | string | yes | Must satisfy policy: ≥8 chars, upper+lower+digit+symbol (FR-016) |
| `role` | enum `admin`\|`reviewer` | yes | (FR-004) |

`client_id` is NOT accepted from the client — it is taken from the acting admin's token.

**UserUpdate** (request; PATCH semantics, all optional):
| Field | Type | Notes |
|-------|------|-------|
| `role` | enum `admin`\|`reviewer` | Triggers last-admin + escalation checks |
| `is_active` | boolean | Triggers last-admin check on deactivate |

Email and password are not changed via this admin endpoint in this spec (self-service password
change is out of scope; reset flow deferred).

## POST /users — create user

| Status | When | Body |
|--------|------|------|
| 201 | Created in admin's client | `UserRead` |
| 400 | Password fails policy | `{ "detail": "PASSWORD_POLICY" }` (message lists the rule) |
| 409 | Email already in use (any client) | `{ "detail": "USER_ALREADY_EXISTS" }` (non-leaking, FR-007/D12) |
| 401/403 | Not authenticated / not admin | — |

Emits `UserCreated` (actor = admin). New user belongs to the admin's `client_id`.

## GET /users — list users (client-scoped)

Returns only users whose `client_id` equals the admin's. Supports optional pagination params
(`limit`, `offset`); defaults are implementation detail.

| Status | When | Body |
|--------|------|------|
| 200 | Authenticated admin | `[ UserRead, ... ]` (own client only, SC-003) |
| 401/403 | Not authenticated / not admin | — |

## PATCH /users/{id} — change role and/or active status

`{id}` must belong to the admin's client, else 404.

| Status | When | Body |
|--------|------|------|
| 200 | Updated | `UserRead` |
| 404 | Target not in admin's client (or absent) | `{ "detail": "USER_NOT_FOUND" }` (no cross-tenant reveal) |
| 409 | Would remove the last active admin of the client (deactivate or demote) | `{ "detail": "LAST_ADMIN" }` (FR-013) |
| 401/403 | Not authenticated / not admin | — |

Emits `UserRoleChanged` (on role change) and/or `UserDeactivated` (on `is_active=false`),
actor = admin. No hard delete endpoint — deactivation only (FR-008).

## Cross-tenant & escalation guarantees (contract-level)

- A token issued for client A can never read or mutate a client-B user → 404/403; zero
  cross-tenant access (SC-003).
- Non-admins never reach these endpoints (`require_admin`), so no user can change roles,
  including their own (FR-014).
