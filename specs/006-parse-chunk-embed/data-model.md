# Data Model: Parse, Chunk & Embed — RAG Index Build

Phase 1 output. Three new tables in Alembic migration **`0006`**, plus `CREATE EXTENSION IF NOT
EXISTS vector`. **No Spec-4 table is altered.** All tables carry `client_id` for tenant scoping
(D2). ORM lives in `app/embedding/models.py` (mirrors `app/ingestion/models.py`); enums in
`app/embedding/enums.py` as `StrEnum` mirrored by DB `CHECK` constraints (the spec-3/4 pattern).

---

## Enums (StrEnum + CHECK)

**ChunkType** — `text` · `table` · `figure_caption` · `structured_data` (FR-002).

**DocumentIndexStatus** — `not_indexed` · `indexed` · `indexed_empty` · `errored_transient` ·
`errored_permanent` (FR-010/FR-011). `errored_transient` is eligible for retry; `errored_permanent`
is skipped on re-runs.

**IndexBuildRunStatus** — `running` · `success` · `partial_success` · `failed` (mirrors
`IngestionRunStatus`).

---

## Table: `chunks`

The atomic unit of retrieval. One row per chunk; cascade-deleted with its document (FR-020).

| Column | Type | Notes |
|--------|------|-------|
| `id` | BigInteger PK | autoincrement |
| `client_id` | BigInteger, FK `clients.id` ON DELETE CASCADE, NOT NULL | tenant scope (FR-014) |
| `document_id` | BigInteger, FK `documents.id` ON DELETE CASCADE, NOT NULL | parent paper |
| `ordinal` | Integer, NOT NULL | 0-based parse order within the document (D5) |
| `chunk_type` | String(16), NOT NULL, CHECK ∈ ChunkType | FR-002 |
| `section` | String(255), NULL | section label where the source has structure; NULL otherwise (FR-002) |
| `drug` | String(255), NULL | **always NULL in v1** (FR-023); populated by Spec 8 |
| `date` | DateTime(tz), NULL | inherited from `documents.published_at` (D3) |
| `source_reliability` | String(20), NOT NULL, CHECK ∈ SourceReliability | inherited from the document (FR-007) |
| `text` | Text, NOT NULL | the chunk text (stored faithfully; redaction = Spec 12) |
| `embedding` | `Vector(768)`, NOT NULL | dense L2-normalized embedding (FR-005/FR-016) |
| `text_tsv` | `tsvector`, **GENERATED ALWAYS AS** `to_tsvector('english', text)` STORED | lexical leg (D4, FR-015) |
| `embedder_version` | String(64), NOT NULL | `result["model_version"]["sha256"]` from the `/embed` result dict (D7, FR-007); same sha256 verified at startup |
| `created_at` | DateTime(tz), server_default now(), NOT NULL | |

**Constraints / indexes**
- `UNIQUE (document_id, ordinal)` — idempotency/dedup guard (D10/D11); a re-attempt cannot duplicate.
- `ix_chunks_client_id` (`client_id`) — tenant-scoped reads (FR-014).
- `ix_chunks_document_id` (`document_id`) — chunk-set lookup / cascade.
- `ix_chunks_client_chunk_type` (`client_id`, `chunk_type`) — Spec-7 filtering (FR-015).
- `ix_chunks_text_tsv` **GIN** (`text_tsv`) — lexical retrieval (FR-015).
- `ix_chunks_embedding_hnsw` **HNSW** (`embedding` `vector_cosine_ops`, m=16, ef_construction=64) —
  dense retrieval (D1, FR-015).
- **No `drug` index in v1** — deferred to Spec 8 (FR-015/FR-023).

## Table: `document_index_state`

1:1 with `documents`; the per-document progress record enabling idempotent / incremental / resumable
/ cause-aware builds (FR-009/FR-010/FR-011/FR-013).

| Column | Type | Notes |
|--------|------|-------|
| `id` | BigInteger PK | autoincrement |
| `document_id` | BigInteger, FK `documents.id` ON DELETE CASCADE, NOT NULL, **UNIQUE** | 1:1 with documents |
| `client_id` | BigInteger, NOT NULL | tenant scope (D2) |
| `status` | String(20), NOT NULL, server_default `not_indexed`, CHECK ∈ DocumentIndexStatus | FR-010 |
| `embedder_version` | String(64), NULL | the version used when last indexed (NULL until indexed) |
| `chunk_count` | Integer, NOT NULL, server_default 0 | chunks produced (0 for indexed_empty) |
| `attempts` | Integer, NOT NULL, server_default 0 | incremented per processing attempt |
| `last_error` | Text, NULL | last failure message (cause kept in `status`); PII-free |
| `last_run_id` | BigInteger, FK `index_build_runs.id` ON DELETE SET NULL, NULL | run that last touched it |
| `updated_at` | DateTime(tz), server_default now(), NOT NULL | |

**Constraints / indexes**
- `UNIQUE (document_id)` — enforces 1:1.
- `ix_document_index_state_client_id` (`client_id`).
- `ix_document_index_state_client_status` (`client_id`, `status`) — the hot "find not-indexed /
  retryable documents for client X" scan (FR-009/FR-011).

**State transitions**
```
not_indexed ──parse+embed+persist (atomic)──▶ indexed
not_indexed ──parses, yields 0 chunks───────▶ indexed_empty
not_indexed ──transient failure─────────────▶ errored_transient ──retry next run──▶ (not_indexed→…)
not_indexed ──parse failure─────────────────▶ errored_permanent  (terminal; skipped on re-runs)
errored_transient ──retry──▶ indexed | indexed_empty | errored_permanent
```
A row is created lazily (status `not_indexed`) the first time a document is considered for indexing.
`indexed`, `indexed_empty`, `errored_permanent` are skipped by subsequent runs; `not_indexed` and
`errored_transient` are picked up.

## Table: `index_build_runs`

One row per index-build invocation for a client; observability + the one-in-flight guard
(FR-010/FR-026). Parallels `ingestion_runs`.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BigInteger PK | autoincrement |
| `client_id` | BigInteger, FK `clients.id`, NOT NULL | tenant scope |
| `triggered_by_user_id` | BigInteger, FK `users.id` ON DELETE SET NULL, NULL | the staff actor |
| `status` | String(16), NOT NULL, server_default `running`, CHECK ∈ IndexBuildRunStatus | |
| `started_at` | DateTime(tz), server_default now(), NOT NULL | |
| `finished_at` | DateTime(tz), NULL | |
| `documents_processed` | Integer, NOT NULL, server_default 0 | |
| `chunks_created` | Integer, NOT NULL, server_default 0 | |
| `documents_skipped` | Integer, NOT NULL, server_default 0 | already-indexed / permanently-errored |
| `documents_errored` | Integer, NOT NULL, server_default 0 | transient + permanent this run |

**Constraints / indexes**
- **Partial UNIQUE** `(client_id) WHERE status = 'running'` — at most one in-flight build per client
  (D10, FR-026); a concurrent trigger detects this and returns the existing run.
- `ix_index_build_runs_client_id` (`client_id`).
- `ix_index_build_runs_status` (`status`).

---

## Relationships & lifecycle

- `chunks.document_id → documents.id` (CASCADE): erasing a document (or client) purges its chunks
  (FR-020); Spec-12 right-to-erasure of vectors rides this cascade.
- `document_index_state.document_id → documents.id` (CASCADE, UNIQUE): 1:1; purged with the document.
- `index_build_runs.client_id → clients.id`: client cascade removes run history.
- **Inactive lifecycle (FR-020)**: a **suspended client** is stopped at the trigger (`acting_client`
  400s `CLIENT_SUSPENDED`); a **deactivated watchlist** is enforced in document selection —
  `get_documents_to_index` excludes documents with no `document_watchlists` link to a
  `watchlists.is_active = true` row (a doc still linked to ≥1 active watchlist is still indexed). Existing
  chunks/state are preserved either way — no destructive delete in this spec.

## Pydantic boundary (no ORM returned from routes)

- `IndexBuildRunOut` — `id, client_id, status, started_at, finished_at, documents_processed,
  chunks_created, documents_skipped, documents_errored`.
- `DocumentIndexStateOut` — `document_id, status, chunk_count, embedder_version, attempts,
  updated_at` (last_error included only for staff detail reads).
- Internal `ParsedChunk` dataclass (parser output, not persisted directly): `text, chunk_type,
  section, ordinal` — embedding/metadata are attached by the runner before insert.

## Migration `0006` (additive, reversible)

- **upgrade**: `CREATE EXTENSION IF NOT EXISTS vector`; create `chunks`, `document_index_state`,
  `index_build_runs` with the columns/constraints/indexes above (including the GENERATED `tsvector`
  column, GIN, and HNSW indexes, and the partial unique index).
- **downgrade**: drop the three tables (reverse FK order) and their indexes. Leave the `vector`
  extension in place (dropping a shared extension is unsafe if other objects use it; documented in
  the migration). Verified up **and** down on the live DB (`test_migration_0006`).
