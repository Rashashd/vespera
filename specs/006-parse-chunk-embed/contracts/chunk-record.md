# Contract: Persisted Chunk Record

The durable shape of a `chunks` row (FR-007, FR-014, FR-016). See [data-model.md](../data-model.md)
for full column types/indexes.

## Required fields (every chunk)
- `client_id` — equals the build's client; tenant scope (FR-014).
- `document_id` — the parent paper (cascade-linked).
- `ordinal` — 0-based position within the document; unique per `(document_id, ordinal)`.
- `chunk_type` ∈ {text, table, figure_caption, structured_data}.
- `section` — label or NULL.
- `source_reliability` — inherited from the document.
- `text` — non-empty chunk text (stored faithfully; not redacted here — Spec 12).
- `embedding` — exactly **768** floats, L2-normalized (from the modelserver). A vector of any other
  dimension MUST cause an error and MUST NOT be persisted (FR-016).
- `text_tsv` — generated `to_tsvector('english', text)` (FR-015; never NULL/empty for non-empty text).
- `embedder_version` — `result["model_version"]["sha256"]` from the `/embed` result dict that produced
  the vector (FR-007); the same sha256 verified against `settings.embedder_model_version` at startup.

## v1 nulls / deferrals
- `drug` — **NULL in v1** (FR-023); no index in v1 (FR-015). Spec 8 populates + indexes it.
- `date` — `documents.published_at` (may be NULL).

## Invariants
- A document marked `indexed` has a contiguous chunk set `ordinal = 0..n-1` committed in the **same
  transaction** as the state transition (FR-028) — no partial sets.
- Re-running a build creates **0** new chunks for an already-`indexed` document (FR-009); the
  `(document_id, ordinal)` unique constraint is the last-line guard.
- Every chunk for a document carries that document's single chosen-source `source_reliability`
  (one paper = one chunk set, FR-024).
