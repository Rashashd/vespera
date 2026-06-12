# Data Model: Hybrid RAG Retrieval & Multi-Source Corroboration

Phase 1 output. **No Alembic migration and no new table** — retrieval reads Spec 6's `chunks` and
Spec 4's `documents`/`document_sources`. This document defines the **read projections** (Pydantic
boundary objects), the **transient Redis cache entry**, the **eval golden-set record**, and the
**manifest artifact additions** for the reranker. ORM/Pydantic live in `app/rag/schemas.py`; the
modelserver schemas in `modelserver/schemas.py`.

---

## Consumed (read-only) entities — unchanged

- **`chunks`** (Spec 6): `id, client_id, document_id, ordinal, chunk_type, section, drug (NULL v1),
  date, source_reliability, text, embedding Vector(768), text_tsv (GENERATED), embedder_version,
  created_at`. Indexes used: `ix_chunks_client_id`, `ix_chunks_embedding_hnsw` (vector_cosine_ops),
  `ix_chunks_text_tsv` (GIN), `ix_chunks_client_chunk_type`.
- **`documents`** (Spec 4): `id, client_id, normalized_external_id, source_reliability, title,
  published_at, …` + relationship `sources`. Used for citation metadata.
- **`document_sources`** (Spec 4): `document_id, source` (e.g. `pubmed`/`europepmc`/…),
  `source_external_id, source_reliability`. Used to list the contributing source name(s) per document.
- **`clients`** (Spec 3/4b): scope + suspended state (enforced via `acting_client`).

No column is added or altered on any of these.

---

## Request boundary — `RetrieveRequest` (Pydantic, `app/rag/schemas.py`)

| Field | Type | Notes |
|-------|------|-------|
| `query` | `str` (min_length 1, max_length 1024, non-blank) | the natural-language query (FR-001); validated non-empty |
| `top_k` | `int` (ge 1, le 50, default 10) | bounded result size (FR-009, D9) |
| `chunk_types` | `list[ChunkType] \| None` | optional filter (FR-019) |
| `source_reliabilities` | `list[SourceReliability] \| None` | optional filter (FR-019) |
| `date_from` / `date_to` | `datetime \| None` | optional publication-date range (FR-019) |

`client_id` is **not** a body field — it comes from the path + `acting_client` (FR-002/FR-021). Drug
filtering is intentionally absent (chunks.drug NULL until Spec 8).

## Result item — `RetrievedPassage`

| Field | Type | Source |
|-------|------|--------|
| `chunk_id` | `int` | `chunks.id` (anchor, FR-012) |
| `document_id` | `int` | `chunks.document_id` (anchor) |
| `ordinal` | `int` | `chunks.ordinal` (position within document, anchor) |
| `chunk_type` | `str` | `chunks.chunk_type` |
| `section` | `str \| None` | `chunks.section` |
| `text` | `str` | `chunks.text` (the citable passage) |
| `score` | `float` | reranker relevance score (D5) |
| `rank` | `int` | 1-based final rank after rerank (FR-010) |
| `source_reliability` | `str` | `chunks.source_reliability` |
| `title` | `str \| None` | `documents.title` (provenance, FR-011) |
| `external_id` | `str` | `documents.normalized_external_id` (provenance) |
| `date` | `datetime \| None` | `documents.published_at` (provenance) |
| `sources` | `list[str]` | `document_sources.source` names for the document (provenance) |

## Corroboration item — `CorroborationSource`

| Field | Type | Notes |
|-------|------|-------|
| `document_id` | `int` | distinct source document in the result set (FR-013) |
| `title` | `str \| None` | citation |
| `external_id` | `str` | `normalized_external_id` |
| `date` | `datetime \| None` | `published_at` |
| `source_reliability` | `str` | inherited |
| `sources` | `list[str]` | contributing feed/source names |
| `passage_chunk_ids` | `list[int]` | the kept chunk ids from this document (lets the UI deep-link all passages) |

## Response boundary — `RetrieveResponse`

| Field | Type | Notes |
|-------|------|-------|
| `query_hash` | `str` | sha256 prefix of the normalized query (correlation; no raw text — FR-023) |
| `embedder_version` | `str` | the embedder sha256 used (FR-004 transparency) |
| `results` | `list[RetrievedPassage]` | ranked top-K (length ≤ `top_k`) |
| `corroboration_count` | `int` | number of distinct source documents in `results` (FR-014) |
| `corroboration_sources` | `list[CorroborationSource]` | **ALL** distinct sources — never truncated (FR-015) |

**Empty corpus / no matches** → `results = []`, `corroboration_count = 0`, `corroboration_sources = []`,
HTTP 200 (FR-015/SC-007). **Version mismatch** → no body; HTTP 409 `EMBEDDER_VERSION_MISMATCH` (D8).

---

## Transient — Redis query-embedding cache entry (not durable)

- **Key**: `rag:qemb:{embedder_sha256}:{sha256(normalized_query)}` (D7).
- **Value**: JSON `list[float]` of length 768.
- **TTL**: `settings.query_embedding_cache_ttl` seconds (default 3600).
- **Lifecycle**: write-through on embed; auto-expire; auto-invalidated by embedder-version key segment
  (FR-017). Best-effort — absence or Redis error never fails a query (FR-018).

## Settings addition (non-secret)

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `query_embedding_cache_ttl` | `int` | `3600` | non-secret config; `extra="forbid"` requires it be declared in `Settings`. Not in Vault, not in `_REQUIRED_SECRETS`. |

---

## Eval golden-set record — `eval/rag/golden_set.jsonl` (one JSON object per line)

| Field | Type | Notes |
|-------|------|-------|
| `query` | `str` | the evaluation query |
| `relevant_document_keys` | `list[str]` | `normalized_external_id`s of the documents that should be retrieved (for hit@k / MRR) |
| `expected_corroboration_count` | `int \| null` | expected distinct-source count for corroboration cases (null if not a corroboration case) |

The eval seeds documents keyed by `normalized_external_id` so cases reference stable keys. Metrics
(D12): **hit@5** (fraction of cases with ≥1 relevant doc among top-5 distinct documents), **MRR** (mean
reciprocal rank of the first relevant document), **corroboration_accuracy** (fraction of corroboration
cases where reported count == expected). Thresholds in `eval_thresholds.yaml[rag]`:
`hit_at_5: 0.85, mrr: 0.70, corroboration_accuracy: 1.0`.

---

## Modelserver manifest additions — `modelserver/models/manifest.json`

Append two artifacts to the existing `artifacts` array (each auto-validated by `validate_artifacts()`
at boot — SHA-256 mismatch/missing → refuse boot):

```jsonc
{ "name": "reranker", "file": "reranker.onnx", "format": "onnx",
  "version": "v1.0-ms-marco-minilm-l6-int8", "sha256": "<sha256 of reranker.onnx>", "max_tokens": 512 }
{ "name": "reranker_tokenizer", "file": "reranker_tokenizer.json", "format": "tokenizer",
  "version": "v1.0-bert-wordpiece", "sha256": "<sha256 of reranker_tokenizer.json>" }
```

The reranker's `model_version` (name/version/sha256) is returned per-result by `POST /rerank`
(`Manifest.model_version("reranker")`), exactly like classifier/embedder stamps.

## Modelserver request/response schemas — `modelserver/schemas.py` (additions)

- **`RerankRequest`**: `query: str`, `passages: list[str] = Field(max_length=128)`.
- **`RerankResult`**: `score: float`, `model_version: ModelVersion`.
- **`RerankResponse`**: `model_version: ModelVersion`, `results: list[RerankResult]` (input order).

## App-side modelserver client — `app/infra/modelserver_client.py` (additions)

- `async def rerank(self, query: str, passages: list[str]) -> list[dict]` → `resp["results"]`
  (each `{ "score", "model_version" }`) in input order; `[]` for empty passages.
- `async def rerank_chunked(self, query, passages)` → split passages into ≤ 128 batches (same `query`
  each), concatenate.

---

## Validation rules (enforced in code, asserted by tests)

- **Isolation (Principle V)**: every dense/lexical query carries `WHERE client_id = :cid`; no result may
  reference another client's chunk (SC-004).
- **Determinism (FR-010)**: identical corpus+query → identical ordering (fixed RRF k, `id` tie-break,
  single-thread ONNX rerank).
- **Corroboration completeness (FR-015)**: `len(corroboration_sources) == corroboration_count ==`
  number of distinct `document_id`s among `results`; never truncated.
- **Version safety (FR-004)**: if the client has chunks and the current embedder sha256 ≠ the sole
  stored `embedder_version`, refuse (409) — no scoring against incomparable vectors.
- **PII-free (FR-023)**: logs bind `client_id` + `query_hash`; never raw query/passage text.
</content>
