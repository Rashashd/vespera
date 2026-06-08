# API Contract: Watchlist Management

Base path: `/watchlists`. **Writes require `require_admin`; reads use `current_active_user`**
(reviewer may view, not modify — FR-013). All operations are scoped to the acting user's
`client_id` (FR-004); a watchlist of another client is invisible → **404** (no reveal, SC-003).
`client_id` is never accepted from the body. Mutations emit audit events.

## Schemas

**WatchlistItem** (embedded):
```json
{ "id": 10, "item_type": "drug", "value": "atorvastatin" }
```

**WatchlistRead** (response):
```json
{ "id": 5, "client_id": 3, "name": "Oncology portfolio",
  "cadence": "weekly", "severity_threshold": "serious",
  "budget_amount": "500.0000", "is_active": true,
  "budget_status": "ok", "current_period_spend": "0.0000",
  "items": [ { "id": 10, "item_type": "drug", "value": "atorvastatin" } ],
  "created_at": "2026-06-06T10:00:00Z" }
```
`budget_status` ∈ `ok|warning|soft_capped` is **derived** (data-model.md); `null` budget ⇒ `ok`.

**WatchlistCreate** (request):
| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `name` | string | yes | Unique per client (case-insensitive) |
| `cadence` | enum | no | default `weekly` |
| `severity_threshold` | enum | no | default `serious` |
| `budget_amount` | number ≥ 0 | no | null = no cap |
| `items` | array of `{item_type, value}` | yes, **≥1** | Empty ⇒ 400 `WATCHLIST_EMPTY` (FR-016) |

**WatchlistUpdate** (request; PATCH, all optional): `name`, `cadence`, `severity_threshold`,
`budget_amount`, `is_active`. Emits one `WatchlistUpdated` (or `WatchlistDeactivated` when
`is_active` flips to false) carrying the changed fields.

**WatchlistItemAdd** (request): `{ "item_type": "drug|mesh|keyword", "value": "..." }`.

## Endpoints

### POST /watchlists — create a named watchlist (with ≥1 item)
| Status | When | Body |
|--------|------|------|
| 201 | Created in caller's client | `WatchlistRead` |
| 400 | `items` empty | `{ "detail": "WATCHLIST_EMPTY" }` |
| 409 | Name already used in this client | `{ "detail": "WATCHLIST_NAME_TAKEN" }` |
| 422 | Bad cadence/severity/budget | validation error |
| 401/403 | Not authenticated / not admin | — |

Emits `WatchlistCreated`. Duplicate items within the payload are de-duplicated (FR-005).

### GET /watchlists — list the caller's client's watchlists
Query: `include_inactive` (bool, default false), `limit`, `offset`.
| Status | When | Body |
|--------|------|------|
| 200 | Authenticated active user | `[WatchlistRead, ...]` (own client only, SC-003) |
| 401 | Not authenticated | — |

### GET /watchlists/{id} — retrieve one
| Status | When | Body |
|--------|------|------|
| 200 | Belongs to caller's client | `WatchlistRead` |
| 404 | Not in caller's client (or absent) | `{ "detail": "WATCHLIST_NOT_FOUND" }` |

### PATCH /watchlists/{id} — rename / set cadence / severity / budget / deactivate
| Status | When | Body |
|--------|------|------|
| 200 | Updated | `WatchlistRead` |
| 400 | Deactivating is fine; **activating** an empty watchlist | `{ "detail": "WATCHLIST_EMPTY" }` |
| 404 | Cross-tenant / absent | `{ "detail": "WATCHLIST_NOT_FOUND" }` |
| 409 | New name collides in client | `{ "detail": "WATCHLIST_NAME_TAKEN" }` |
| 422 | Bad enum/budget value | validation error |
| 401/403 | Not authenticated / not admin | — |

Deactivation is **soft-delete** (FR-017): `is_active=false`, data preserved, excluded from
monitoring; emits `WatchlistDeactivated`. No hard-delete endpoint exists.

### POST /watchlists/{id}/items — add an item (idempotent)
| Status | When | Body |
|--------|------|------|
| 201 | Item added | `WatchlistRead` |
| 200 | Item already present (idempotent no-op) | `WatchlistRead` |
| 404 | Cross-tenant / absent watchlist | `{ "detail": "WATCHLIST_NOT_FOUND" }` |
| 401/403 | Not authenticated / not admin | — |

Emits `WatchlistItemAdded` only when a row is actually created.

### DELETE /watchlists/{id}/items/{item_id} — remove an item (graceful)
| Status | When | Body |
|--------|------|------|
| 204 | Removed, or already absent (graceful) | — |
| 400 | Would leave an **active** watchlist empty | `{ "detail": "WATCHLIST_EMPTY" }` |
| 404 | Cross-tenant / absent watchlist | `{ "detail": "WATCHLIST_NOT_FOUND" }` |
| 401/403 | Not authenticated / not admin | — |

Emits `WatchlistItemRemoved` when a row is deleted.

## Budget behavior (contract-level)

- `budget_status` and `current_period_spend` in `WatchlistRead` reflect the **current UTC month**.
- Spend is recorded by later specs; in this spec it is observable/derived and exercised by tests.
- One watchlist reaching `soft_capped` does not change any sibling watchlist's status (FR-011).
- Raising `budget_amount` above current spend flips `soft_capped`→`ok` with no extra write; a new
  UTC month resets the period (no usage row ⇒ `ok`) (FR-012).

## Guarantees

- Cross-tenant access impossible: every query filters by the token's `client_id`; mismatches 404.
- Every create/update/deactivate/item-change → exactly one audit row, actor = acting admin (SC-008).
