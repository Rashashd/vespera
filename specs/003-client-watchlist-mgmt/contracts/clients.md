# API Contract: Client (Tenant) Management

Tenant **onboarding** (create / suspend / reactivate) is an **operator script**, not an API
(research D1, avoids admin self-lockout). The API exposes only the acting admin's *own* client.
`client_id` always comes from the token.

## Operator path: `scripts/seed_client.py`

Run by a platform operator (not reachable over HTTP). Mirrors the spec-2 `seed_admin.py` pattern.

| Action | Invocation (illustrative) | Effect | Audit |
|--------|---------------------------|--------|-------|
| Create | `uv run python scripts/seed_client.py --name "Acme Pharma"` | Insert active client; print its id | `ClientCreated` (actor = system sentinel 0) |
| Suspend | `... --suspend <client_id>` | Set `status='suspended'`; config treated inactive downstream | `ClientSuspended` |
| Reactivate | `... --activate <client_id>` | Set `status='active'` | `ClientUpdated` |

- Duplicate (case-insensitive) name → exits non-zero with a clear message (DB unique violation).
- No destructive delete (FR-002): suspend only.

## Schemas

**ClientRead** (response):
```json
{ "id": 3, "name": "Acme Pharma", "status": "active",
  "created_at": "2026-06-06T10:00:00Z", "updated_at": "2026-06-06T10:00:00Z" }
```

**ClientUpdate** (request; PATCH, all optional):
| Field | Type | Notes |
|-------|------|-------|
| `name` | string | Trimmed; must stay platform-unique (case-insensitive) |

`status` is **not** settable via the API (operator-only) to prevent self-suspension.

## GET /clients/me — read the caller's own client

Guard: `current_active_user` (admin **or** reviewer of the client may view; FR-013).

| Status | When | Body |
|--------|------|------|
| 200 | Authenticated active user | `ClientRead` for the caller's `client_id` |
| 401 | Not authenticated | — |

## PATCH /clients/me — rename the caller's own client

Guard: `require_admin` (only admin may modify; FR-013).

| Status | When | Body |
|--------|------|------|
| 200 | Updated | `ClientRead` |
| 409 | New name already in use (any client) | `{ "detail": "CLIENT_NAME_TAKEN" }` |
| 422 | Empty/invalid name | validation error |
| 401/403 | Not authenticated / not admin | — |

Emits `ClientUpdated` (actor = admin), audited in the same transaction.

## Guarantees

- A caller can only ever read/modify **their own** client; there is no endpoint that takes a
  client id, so cross-tenant client access is structurally impossible via the API (SC-003).
- All mutations produce exactly one audit row attributed to the correct actor (SC-008).
