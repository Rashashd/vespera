# Contract: Read Finding Triage State (FR-013)

HTTP read endpoint exposing a finding's triage outcome. Mirrors the spec-7 route style
(`app/rag/routes.py`): `APIRouter(prefix="/clients/{client_id}")`, `get_acting_client` dependency,
Pydantic response (never an ORM object), client-scoped.

## Request

```
GET /clients/{client_id}/findings/{finding_id}
Authorization: Bearer <JWT>
```

- Auth: any authenticated staff or authorized client-user (no `require_admin`), same as `/search`.
- `get_acting_client` resolves + authorizes the target client; suspended client → 400 `CLIENT_SUSPENDED`.

## Response 200 — `FindingStateResponse`

```json
{
  "finding_id": 123,
  "client_id": 7,
  "document_id": 456,
  "drug": "atorvastatin",
  "reaction": "rhabdomyolysis",
  "bucket": "urgent",
  "status": "pending_expedited",
  "model_confidence": 0.82,
  "resolution_path": "model",
  "created_at": "2026-06-12T10:01:00Z"
}
```

- `corroboration_sources` is intentionally **not** exposed here (null until spec 9).
- `bucket` ∈ irrelevant|positive|minor|urgent|emergency; `status` ∈ pending_expedited|pending_batch|classified;
  `resolution_path` ∈ model|llm|escalated.

## Errors

| Status | Detail | When |
|--------|--------|------|
| 400 | `CLIENT_SUSPENDED` | acting client is suspended |
| 403 | (role/scope) | caller not authorized for this client |
| 404 | `FINDING_NOT_FOUND` | no finding with that id under this client (client-scoped lookup — never leak cross-tenant existence) |

## Invariants

- Lookup is filtered by `client_id` from the resolved acting client (Principle V); a finding belonging
  to another client returns 404, not 403, to avoid cross-tenant existence disclosure.
