# Contract: Retrieval pipeline (dense + lexical + RRF fusion)

Internal contract for `app/rag/retrieval.py` and `app/rag/fusion.py`. All queries are
`client_id`-scoped (Principle V).

## Dense candidates (`retrieval.dense_candidates`)

- Input: `client_id`, query vector `qvec` (768, L2-normalized), `n` (default 50), optional filters.
- Sets `SET LOCAL hnsw.ef_search = 100` on the transaction (D2).
- SQL shape:
  ```sql
  SELECT id, document_id, ordinal, chunk_type, section, text, source_reliability, date
  FROM chunks
  WHERE client_id = :cid
    [AND chunk_type = ANY(:types)] [AND source_reliability = ANY(:rels)]
    [AND date >= :date_from] [AND date <= :date_to]
  ORDER BY embedding <=> :qvec
  LIMIT :n;
  ```
- Output: ordered list of candidate rows (rank = position, 0-based) — uses `ix_chunks_embedding_hnsw`.

## Lexical candidates (`retrieval.lexical_candidates`)

- Input: same, with the raw `query` string.
- Builds `q := websearch_to_tsquery('english', :query)` (D3; `'english'` MUST match the Spec-6
  `text_tsv` config).
- SQL shape:
  ```sql
  SELECT id, …, ts_rank_cd(text_tsv, q) AS rank_score
  FROM chunks, websearch_to_tsquery('english', :query) AS q
  WHERE client_id = :cid AND text_tsv @@ q
    [AND … same optional filters …]
  ORDER BY rank_score DESC, id ASC
  LIMIT :n;
  ```
- Output: ordered list (rank = position) — uses `ix_chunks_text_tsv` (GIN). Empty when no lexical match
  (semantic-only queries) — that is expected; dense leg still contributes.

## Fusion (`fusion.reciprocal_rank_fusion`)

- Input: the two ranked candidate lists, RRF constant `k = 60`.
- `fused_score(chunk) = Σ_leg 1 / (k + rank_leg(chunk))` over the legs the chunk appears in.
- Sort by `fused_score` desc, **tie-break `chunk.id` asc** (FR-010, determinism).
- Output: a single fused, de-duplicated candidate list (a chunk in both legs appears once with summed
  contribution). The fused pool (≤ 2·n distinct) is what gets reranked.

## Determinism contract (FR-010)

- Same corpus + same query ⇒ identical fused ordering: fixed `k`, explicit `id` tie-break in both legs
  and in fusion, no wall-clock or random input.

## Isolation contract (Principle V / SC-004)

- Both candidate queries MUST include `WHERE client_id = :cid`. No code path may issue an unscoped
  chunk query. Integration test seeds two clients with overlapping text and asserts zero foreign rows.
</content>
