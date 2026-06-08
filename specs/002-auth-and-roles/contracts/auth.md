# API Contract: Authentication

Base path: `/auth/jwt`. All bodies JSON unless noted. Stateless JWT bearer tokens (HS256, ~30 min).
These are contracts (shapes + status codes), not implementation.

## POST /auth/jwt/login

Authenticate and obtain an access token. **Rate-limited: 5 requests / minute / source IP**
(FR-010). Custom route (research D7) — emits `UserLoggedIn` / `LoginFailed` audit events.

**Request** (`application/x-www-form-urlencoded`, OAuth2 password flow as fastapi-users expects):

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `username` | string | yes | The user's email (OAuth2 form field name) |
| `password` | string | yes | Plaintext credential (TLS only); never logged |

**Responses**:

| Status | When | Body |
|--------|------|------|
| 200 | Valid credentials, active user | `{ "access_token": "<jwt>", "token_type": "bearer" }` |
| 400 | Bad credentials OR inactive user | `{ "detail": "LOGIN_BAD_CREDENTIALS" }` — generic, does not reveal whether email exists or account is inactive (FR-002) |
| 422 | Missing/malformed fields | Validation error |
| 429 | > 5 attempts in the window | `{ "error": "Rate limit exceeded: 5 per 1 minute" }` (spec-1 handler) (FR-010, SC-004) |

**Token claims**: `sub` = user id, standard `exp` (now + token TTL), `aud` = fastapi-users
audience. Role/client are loaded from the DB on each request (not trusted from client input).

## POST /auth/jwt/logout

Stateless logout. Provided for symmetry; the client discards the token (no server-side session
to revoke).

**Auth**: Bearer token required.

**Responses**:

| Status | When | Body |
|--------|------|------|
| 204 | Authenticated caller | (empty) |
| 401 | No/invalid token | `{ "detail": "Unauthorized" }` |

## Authentication scheme (applies to all protected endpoints)

`Authorization: Bearer <access_token>`.

| Condition | Status |
|-----------|--------|
| Missing / malformed / expired / bad-signature token | 401 Unauthorized (FR-003) |
| Valid token, user since deactivated | 401 Unauthorized (FR-008; effective within ≤ token TTL) |
| Valid token, active user, role permitted | 200/2xx |
| Valid token, active user, role NOT permitted | 403 Forbidden (FR-005) |

The 401-vs-403 distinction is contractually required: unauthenticated = 401, authenticated but
unauthorized = 403.
