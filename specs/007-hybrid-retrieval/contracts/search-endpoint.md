# Contract: `POST /clients/{client_id}/search`

Staff-facing retrieval endpoint. Returns ranked, provenance-carrying passages from one client's chunk
index plus multi-source corroboration. Registered from `app/rag/routes.py` in `app/main.py`.

## Authorization

- `Depends(get_acting_client)` — the **suspended-refusing** acting-client guard (`allow_suspended=False`,
  D10). Resolves and server-validates the target client per request (Principle V control b).
- **No `require_admin`** — any authenticated staff (or authorized client-user) with access to the target
  client may search (Q4 clarification).
- Suspended client → `400 CLIENT_SUSPENDED` (the `acting_client` behavior). Unknown/forbidden client →
  `403`/`404` per existing guard. Missing/invalid JWT → `401`.

## Request

`POST /clients/{client_id}/search`  ·  body = `RetrieveRequest`:

```jsonc
{
  "query": "hepatotoxicity associated with DrugX",   // required, 1..1024 chars, non-blank
  "top_k": 10,                                        // optional, 1..50, default 10
  "chunk_types": ["text", "table"],                   // optional filter
  "source_reliabilities": ["peer_reviewed"],          // optional filter
  "date_from": "2020-01-01T00:00:00Z",                // optional
  "date_to": null                                      // optional
}
```

## Response `200` = `RetrieveResponse`

```jsonc
{
  "query_hash": "9f2c1a……",          // sha256 prefix of normalized query (no raw text)
  "embedder_version": "6bd398……",     // embedder sha256 used
  "results": [
    {
      "chunk_id": 4012, "document_id": 88, "ordinal": 3,
      "chunk_type": "text", "section": "Adverse Reactions",
      "text": "…", "score": 7.42, "rank": 1,
      "source_reliability": "peer_reviewed",
      "title": "Hepatic injury after DrugX", "external_id": "PMID:12345678",
      "date": "2021-05-01T00:00:00Z", "sources": ["pubmed", "europepmc"]
    }
  ],
  "corroboration_count": 3,
  "corroboration_sources": [
    { "document_id": 88, "title": "…", "external_id": "PMID:12345678",
      "date": "2021-05-01T00:00:00Z", "source_reliability": "peer_reviewed",
      "sources": ["pubmed"], "passage_chunk_ids": [4012, 4015] }
    // … ALL distinct sources, never truncated (FR-015)
  ]
}
```

## Status codes

| Code | When |
|------|------|
| `200` | success (including empty corpus → `results: []`, `corroboration_count: 0`) |
| `400` | suspended client (`CLIENT_SUSPENDED`); invalid body (blank query, top_k out of range) |
| `401` | missing/invalid JWT |
| `403` / `404` | actor not authorized for / unknown target client |
| `409` | `EMBEDDER_VERSION_MISMATCH` — client index built with a different embedder; rebuild required (D8) |
| `502` | modelserver embed/rerank failed after retries (`ModelserverError`) |

## Invariants

- Every `results[*]` and `corroboration_sources[*]` belongs to `client_id` (Principle V; SC-004).
- `len(corroboration_sources) == corroboration_count ==` distinct `document_id`s in `results` (FR-014/015).
- `len(results) <= top_k`; `rank` is contiguous 1..len; ordering deterministic (FR-010).
- Response is a validated Pydantic model — never an ORM object (Engineering Standards).
- Logs bind `client_id` + `query_hash`; raw query/passage text is never logged (FR-023).
</content>
