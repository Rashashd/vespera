# Contract: Document Browse

**Feature**: 004-literature-ingestion. JWT required. **Client-scoped** — only the caller's own
client's documents are visible; cross-tenant access returns **404**. **Role**: `admin` + `reviewer`
(both may view; no write endpoints — the corpus is written only by ingestion runs).

---

## GET `/documents`

List the caller's client's documents (the ingested corpus), newest `last_fetched_at` first.

**Query params** (all optional): `watchlist_id` (filter via provenance), `source` (`SourceName`),
`reliability` (`SourceReliability`), `limit` (default 50, max 200), `offset` (default 0).

**Responses**: `200` → `DocumentOut[]`; `400` for malformed filter values.

```jsonc
// 200 DocumentOut (summary form)
{
  "id": 9001,
  "normalized_external_id": "doi:10.1000/jcard.2026.001",
  "source_reliability": "peer_reviewed",
  "title": "Hepatotoxicity associated with DrugX: a cohort study",
  "published_at": "2026-05-30T00:00:00Z",
  "origin_url": "https://doi.org/10.1000/jcard.2026.001",
  "contributing_sources": ["pubmed", "europepmc"],
  "watchlist_ids": [7],
  "first_fetched_at": "2026-06-08T12:00:03Z",
  "last_fetched_at": "2026-06-08T12:00:03Z"
}
```

---

## GET `/documents/{document_id}`

Document detail, including each contributing source's metadata and provenance.

**Responses**: `200` → `DocumentDetailOut`; `404` if not the caller's.

```jsonc
// 200 DocumentDetailOut (adds per-source detail + provenance; raw payloads NOT inlined here)
{
  "id": 9001,
  "normalized_external_id": "doi:10.1000/jcard.2026.001",
  "source_reliability": "peer_reviewed",
  "title": "Hepatotoxicity associated with DrugX: a cohort study",
  "summary": "…abstract…",
  "published_at": "2026-05-30T00:00:00Z",
  "origin_url": "https://doi.org/10.1000/jcard.2026.001",
  "sources": [
    { "source": "pubmed",    "source_external_id": "40123456", "source_reliability": "peer_reviewed",
      "fetched_at": "2026-06-08T12:00:03Z" },
    { "source": "europepmc", "source_external_id": "PMC1234567", "source_reliability": "peer_reviewed",
      "fetched_at": "2026-06-08T12:00:03Z" }
  ],
  "provenance": [ { "watchlist_id": 7, "first_run_id": 42, "created_at": "2026-06-08T12:00:03Z" } ],
  "first_fetched_at": "2026-06-08T12:00:03Z",
  "last_fetched_at": "2026-06-08T12:00:03Z"
}
```

**Notes**:
- `contributing_sources` lists every source that surfaced this paper; `source_reliability` is the
  **highest** among them (FR-005). One paper appears **once** per client even if multiple sources
  or watchlists surfaced it (FR-006).
- Raw source payloads are persisted (for spec-6 parsing) but are **not** returned by these
  read endpoints; they are not logged either (FR-023).

**Acceptance** (spec): US2-1..4, US3-1..4, SC-002, SC-003, SC-004.
