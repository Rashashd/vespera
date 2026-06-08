# Contract: Ingestion Trigger & Runs

**Feature**: 004-literature-ingestion. All endpoints require a valid JWT (spec 2). All are
**client-scoped**: the caller may only act on / read their own client's watchlists and runs;
cross-tenant access returns **404** (no existence reveal). Request/response bodies are Pydantic
models (no ORM leakage). Errors use the platform's standard JSON shape.

---

## POST `/watchlists/{watchlist_id}/ingest`

Manually trigger an ingestion run for one of the caller's **active, non-empty** watchlists.
**Role**: `admin` only (`require_admin`). Reviewers → 403.

**Behavior**: Validates eligibility, creates an `ingestion_runs` row (`status=running`), raises
`IngestionRunTriggered` (audited, exactly one row — FR-016/SC-008), schedules the run as an
in-process background task (D8), and returns immediately.

**Responses**:

| Status | When | Body |
|--------|------|------|
| `202 Accepted` | run started | `IngestionRunOut` (status `running`) |
| `400 Bad Request` | watchlist empty / inactive | `{detail}` (FR-001) |
| `403 Forbidden` | caller is `reviewer` | `{detail}` |
| `404 Not Found` | watchlist missing or other client's | `{detail}` (no reveal) |

```jsonc
// 202 IngestionRunOut
{
  "id": 42,
  "watchlist_id": 7,
  "status": "running",
  "started_at": "2026-06-08T12:00:00Z",
  "finished_at": null,
  "counts": { "fetched": 0, "created": 0, "skipped": 0, "errored": 0 },
  "sources": []
}
```

**Acceptance** (spec): US1-1..5, SC-001, SC-005, SC-008.

---

## GET `/watchlists/{watchlist_id}/ingestion-runs`

List runs for one of the caller's watchlists, newest first. **Role**: `admin` + `reviewer` (view).

**Responses**: `200` → `IngestionRunOut[]`; `404` if the watchlist isn't the caller's.
Supports optional `limit`/`offset` query params (defaults: 50 / 0).

---

## GET `/ingestion-runs/{run_id}`

Run detail including per-source outcomes. **Role**: `admin` + `reviewer` (view).

**Responses**: `200` → `IngestionRunOut` (with populated `sources[]`); `404` if not the caller's.

```jsonc
// 200 IngestionRunOut (terminal)
{
  "id": 42,
  "watchlist_id": 7,
  "status": "partial_success",
  "started_at": "2026-06-08T12:00:00Z",
  "finished_at": "2026-06-08T12:00:09Z",
  "counts": { "fetched": 140, "created": 31, "skipped": 109, "errored": 0 },
  "sources": [
    { "source": "pubmed",        "status": "success", "error": null,
      "counts": { "fetched": 80, "created": 20, "skipped": 60, "errored": 0 } },
    { "source": "europepmc",     "status": "success", "error": null,
      "counts": { "fetched": 60, "created": 11, "skipped": 49, "errored": 0 } },
    { "source": "ema",           "status": "failed",  "error": "timeout after 3 attempts",
      "counts": { "fetched": 0,  "created": 0,  "skipped": 0,  "errored": 0 } }
  ]
}
```

**Status semantics** (FR-011): `success` = all attempted sources succeeded; `partial_success` =
≥1 succeeded and ≥1 failed; `failed` = all failed or could not start; `running` = in progress (and
reconciled to `failed` by the startup sweep if the process stopped — FR-024).

**Acceptance** (spec): US5-1..2, SC-007, SC-011.
