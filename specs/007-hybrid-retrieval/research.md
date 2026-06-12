# Research: Hybrid RAG Retrieval & Multi-Source Corroboration

Phase 0 output. Resolves the deferred/clarified decisions into concrete, defensible choices grounded
in the live codebase (Spec 6's `chunks` index, the modelserver, Redis infra, the `acting_client`
guards). Format per decision: **Decision · Rationale · Alternatives considered**.

---

## D1 — Fusion method (clarified: deferred to planning)

**Decision**: **Reciprocal Rank Fusion (RRF)** with `k = 60`. Run dense and lexical as two separate
`client_id`-scoped queries (top-N each, N = 50), then fuse in Python:
`score(chunk) = Σ_leg 1 / (k + rank_leg(chunk))`. Sort by fused score desc; **deterministic tie-break
on `chunk.id` asc** (FR-010). A chunk present in only one leg still scores from that leg.

**Rationale**: RRF needs **no score normalization** across two incomparable scales (pgvector cosine
distance vs. `ts_rank_cd`), is the standard, robust hybrid-fusion baseline, has a single well-known
constant, and is trivially deterministic — which the eval gate and reproducible citations require. Two
simple queries keep each SQL statement readable (Constitution file-hygiene) and DB-portable.

**Alternatives considered**: *Weighted score blend* (normalize then weight) — rejected as the default:
fragile across query types, needs a tuned weight + min-max normalization, harder to keep deterministic;
kept as a documented future tuning option if the golden set shows RRF underperforming. *Single-SQL
fusion with two CTEs* — equivalent result but a denser statement; deferred unless profiling shows the
two-round-trip cost matters (it won't at this corpus scale).

## D2 — Dense retrieval query

**Decision**: Cosine search over the existing HNSW index `ix_chunks_embedding_hnsw`
(`vector_cosine_ops`). Query: `SELECT id, ... ORDER BY embedding <=> :qvec LIMIT :n` with
`WHERE client_id = :cid` (+ optional filters). The query vector is the embedder's already-L2-normalized
768-dim output, so `<=>` cosine distance is exact. Set `SET LOCAL hnsw.ef_search = 100` on the
retrieval transaction to raise recall above the default 40 (tunable).

**Rationale**: Matches Spec 6's index exactly (`vector_cosine_ops`, m=16, ef_construction=64). pgvector's
`<=>` operator uses the HNSW index for `ORDER BY ... LIMIT`. `client_id` is the leading column of
`ix_chunks_client_id`; the HNSW scan is post-filtered by client — acceptable at this scale and the
isolation guarantee is enforced in the `WHERE` clause (and verified by SC-004 tests).

**Determinism note (FR-010, resolves L3):** HNSW is an *approximate* index, but for a **fixed index
state and a fixed `ef_search`** it returns a **stable, reproducible ordering** — sufficient for the eval
gate and for re-retrieving a cited passage over the static golden corpus. The explicit
`ORDER BY embedding <=> :qvec` plus the `chunk.id` secondary tie-break in fusion pin any ties. Exact
nearest-neighbor recall is NOT claimed in the general (concurrently-mutating) case; the spec's
"deterministic" guarantee is scoped to a fixed index state.

**In SQLAlchemy** use the pgvector comparator: `Chunk.embedding.cosine_distance(qvec)` for `<=>`; set
`ef_search` with `await session.execute(text("SET LOCAL hnsw.ef_search = 100"))` inside the retrieval
transaction.

**Alternatives considered**: IVFFlat — rejected (Spec 6 already chose HNSW). Pre-filtering via a
partitioned/partial index per client — premature; revisit only if cross-client scan cost grows.

## D3 — Lexical retrieval query

**Decision**: Postgres full-text over the existing GIN index `ix_chunks_text_tsv`. Build the query with
**`websearch_to_tsquery('english', :q)`**; rank with **`ts_rank_cd(text_tsv, query)`**:
`WHERE client_id = :cid AND text_tsv @@ q ORDER BY ts_rank_cd(text_tsv, q) DESC LIMIT :n`.

**Rationale**: `websearch_to_tsquery` accepts arbitrary user input safely (no tsquery syntax errors on
punctuation/quotes), supports quoted phrases and `-` negation, and uses `'english'` to match Spec 6's
`STORED GENERATED text_tsv` config (must be the **same** text-search config or the index is unused).
`ts_rank_cd` (cover density) rewards term proximity — good for clinical phrases.

**Alternatives considered**: `plainto_tsquery` (no phrase/operator support) and `to_tsquery` (raises on
malformed input) — both rejected for a user-facing query string. ILIKE/trigram — rejected (no semantic
ranking, ignores the GIN tsvector index).

## D4 — Reranker model (clarified: cross-encoder → ONNX)

**Decision**: Ship a **cross-encoder** reranker — base model **`cross-encoder/ms-marco-MiniLM-L-6-v2`**
— exported to **ONNX and dynamically quantized (INT8)**, committed under `modelserver/models/reranker.onnx`
with its wordpiece tokenizer `reranker_tokenizer.json`. It scores `(query, passage)` pairs → a relevance
logit. Training/export happens **offline in `notebooks/train_reranker.ipynb`** using the dev-only
`training` uv group (torch/transformers/optimum), writing the artifact + its SHA-256 into
`modelserver/models/manifest.json`. No fine-tuning required for v1 (the pretrained MS-MARCO cross-encoder
reranks biomedical passages adequately; a biomedical cross-encoder is a documented future improvement).

**Rationale**: A cross-encoder is the precision-improving reranker the Brief designates as the "one
justified RAG improvement" (§5-D). MS-MARCO MiniLM-L6 is the canonical lightweight reranker; INT8 ONNX
keeps it well within the modelserver's < 500 MB budget (the embedder export `model_quantized.onnx` is
already ~110 MB and total image stays lean). Serving via `onnxruntime` honors the **no-torch** serving
constraint (Principle VI). Offline-export mirrors the established classifier/embedder pattern (Rationale A).

**Alternatives considered**: *LLM-rerank* (clarified fallback) — rejected as primary: depends on the
LLM adapter not built until Spec 9, adds per-query API cost + latency + nondeterminism (hurts the eval
gate). *No reranker / fusion-only* — rejected: drops US4 and the differentiator. *Biomedical
cross-encoder* (e.g. PubMedBERT cross-encoder) — better domain fit but heavier; deferred to future
improvements. **Image-budget guardrail**: if the quantized artifact + runtime ever threatens the
< 500 MB image, fall back to the smaller `ms-marco-MiniLM-L-2-v2` before considering LLM-rerank.

## D5 — Reranker serving (`POST /rerank` on the existing modelserver)

**Decision**: Add `POST /rerank` to `modelserver/routes.py` (guarded by the existing
`require_service_token`, gated on `app.state.ready`). Request: `{ "query": str, "passages": [str, …≤128] }`.
Response: `{ "model_version": ModelVersion, "results": [ { "score": float, "model_version": … }, … ] }`
in input order. Inference in a new `modelserver/inference/reranker.py` (`CrossEncoderSession`): tokenize
each `(query, passage)` pair (truncate to 512), run ONNX, return the relevance logit (sigmoid optional —
order is what matters). Load the session + tokenizer into `app.state` in `modelserver/main.py`; add the
two artifacts to `manifest.json` so **`validate_artifacts()` SHA-256-checks them at boot automatically**
(it iterates all manifest entries — refuses boot on mismatch/missing).

**Rationale**: Reuses every modelserver pattern (token auth, readiness gate, latency window,
per-result `model_version` stamp, startup SHA-256 validation) with zero new infrastructure. Batch ≤ 128
matches `/classify` and `/embed`.

**Alternatives considered**: A separate reranker container — rejected (Constitution VI; the modelserver
is the project's single no-torch inference service). Returning a pre-sorted list from the server —
rejected: the server returns scores in input order; the **caller** owns ordering/top-K policy (mirrors
`/classify` returning raw confidence and the caller owning the cutoff).

## D6 — `ModelserverClient.rerank()`

**Decision**: Add `rerank(query, passages) -> list[dict]` and `rerank_chunked(query, passages)` to
`app/infra/modelserver_client.py`, mirroring `classify`/`embed`: POST `/rerank` via `_post_with_retry`
(tenacity, no retry on 4xx), return `resp["results"]` (each `{ "score", "model_version" }`) in input
order; `rerank_chunked` splits passages into ≤ 128 batches (re-sending the same `query` per batch) and
concatenates. Empty passages → `[]`.

**Rationale**: Consistent with the existing typed client; the retrieval service stays unaware of HTTP.

**Alternatives considered**: Reranking inside `app/rag` with a local ONNX session — rejected: would put
`onnxruntime` (and the artifact) into the `api` image, breaking the lean-app boundary Spec 5 set.

## D7 — Query-embedding cache (Redis, best-effort)

**Decision**: Cache the query vector in the existing Redis (`app.state.redis`). **Key**:
`rag:qemb:{embedder_sha256}:{sha256(normalized_query)}`. **Normalization**: Unicode NFKC → strip → lower
→ collapse internal whitespace. **Value**: JSON-encoded `list[float]` (768). **TTL**:
`settings.query_embedding_cache_ttl` (default **3600 s**), a new non-secret `Settings` field. Flow:
compute key → `GET`; on hit decode and skip the embed call; on miss call `ModelserverClient.embed([q])`,
then `SET … EX ttl`. **Best-effort**: any Redis exception (down, timeout) is caught, logged at warning,
and the query proceeds with a live embed (FR-018). Embedding the empty/whitespace-only query is refused
upstream by request validation.

**Rationale**: Embedder-version in the key auto-invalidates on model change (FR-017) — no stale vector
is ever reused after an upgrade. Hashing the normalized query bounds key size and dedups trivially
different spellings. JSON keeps it inspectable; 768 floats is small. Reusing the existing Redis avoids
new infra.

**Alternatives considered**: Packed `float32` bytes (smaller, faster) — deferred micro-opt; JSON is
clearer for v1. No version in key + explicit invalidation on upgrade — rejected (fragile; the version
key is self-healing). Caching whole result sets — rejected: corpus changes between cycles would serve
stale results; only the *query embedding* is safe to cache.

## D8 — Embedder-version verification (FR-004, fail-fast)

**Decision**: Before scoring, fetch the **current embedder SHA-256** (from
`ModelserverClient.get_ready()["models"]["embedder"]["sha256"]`, cached per-process at app startup) and
the **set of distinct `embedder_version` values** present in the client's chunks
(`SELECT DISTINCT embedder_version FROM chunks WHERE client_id = :cid`). If the client has chunks **and**
the current embedder SHA-256 is not the sole version present, **refuse** the query with a clear error
(HTTP 409 Conflict, code `EMBEDDER_VERSION_MISMATCH`, message: "client index was built with a different
embedder version; rebuild required"). If the client has **no** chunks → not a mismatch (empty result,
D9). The query is embedded with the current embedder regardless; the guard prevents scoring it against
incomparable stored vectors.

**Rationale**: Honors the Q5 clarification (fail-fast, never silently-wrong). Comparing against the
distinct set (not just "any mismatch") cleanly handles the normal case (all chunks one version) and the
upgrade case (mixed/old versions → refuse until Spec 6 re-index).

**Source of the current embedder SHA — NO `/ready` call, NO boot coupling (resolves C2):** every
`/embed` response already returns `model_version.sha256` (exactly as Spec-6's `app/embedding/runner.py`
reads it). The guard embeds the query, reads that sha, and compares it to the client's distinct
`chunks.embedder_version`. The sha is **memoized on `app.state.embedder_sha`** after the first embed,
optionally seeded from the OPTIONAL `settings.embedder_model_version` pin — which is **empty by default**
(it is declared in `Settings` but is NOT loaded in `app/core/startup.py`, so do not rely on it). The
memoized sha builds the US5 cache key before embedding; on a cold memo the first query simply skips the
cache lookup, embeds, then populates the memo. **The api never calls the modelserver at startup.**

**Alternatives considered**: Per-row version compare during ranking — rejected (can't return partial
silently-wrong results). Degrade-to-lexical on mismatch (Q5 option B) — rejected by the clarification.

## D9 — Result projection, top-K, and corroboration grouping

**Decision**: After rerank, take **top-K (default 10, max 50)**. For each kept chunk build a
`RetrievedPassage`: relevance score, final rank (1-based), **anchor** (`chunk_id`, `document_id`,
`ordinal`, `section`, `chunk_type`), text, and **provenance** from a single join to `documents`
(`title`, `published_at` → `date`, `source_reliability`) and `document_sources` (the `source` names that
contributed the document). **Corroboration**: group the *kept* passages by `document_id`; the
`corroboration_count` = number of distinct documents; emit a `CorroborationSource` per distinct document
(`document_id`, `title`, `sources`, `external_id` = `documents.normalized_external_id`, `date`,
`source_reliability`). **All** distinct sources are listed — never truncated (FR-015) — independent of
how many passages or how large top-K is.

**Rationale**: One additional join yields all citation metadata (the `documents`/`document_sources`
shape from Spec 4 carries title, normalized external id, published date, reliability, and source
names). Grouping the returned set (not a separate retrieval) keeps corroboration consistent with what
the reviewer sees and counts a multi-passage paper once (FR-013).

**Alternatives considered**: A separate, wider retrieval purely for corroboration counting — rejected
for v1: would diverge from the cited passages and complicate determinism; corroboration over the
returned top-K is the Brief's "group retrieved chunks by source document" (§3b). (Counting across the
full fused pool rather than top-K is a documented future tuning knob.)

## D10 — Endpoint surface & authorization

**Decision**: `POST /clients/{client_id}/search` in `app/rag/routes.py`, registered in `app/main.py`.
Auth: `Depends(get_acting_client)` (the **suspended-refusing** variant, `allow_suspended=False`) and
**no `require_admin`** — so any authenticated staff (or, later, an authorized client-user) with access
to the target client may search, but a suspended client is refused (US1 scenario 4). Request body =
`RetrieveRequest` (query, optional filters, top_k); response = `RetrieveResponse` (validated Pydantic,
never ORM). The orchestration lives in `app/rag/service.py` (session + redis + modelserver client
injected) so non-HTTP callers (Spec 9 agent tool, Spec 11 worker) reuse it.

**Rationale**: Reconciles the Q4 clarification (any staff role with read access — *not* admin-only) with
US1 scenario 4 (suspended client refused). The role breadth comes from omitting `require_admin`; the
suspended-refusal comes from `get_acting_client` (not `_read`). `acting_client` already enforces
per-request, server-validated client scoping (Principle V control b) and staff-vs-client-user access.

**Alternatives considered**: `get_acting_client_read` (allows suspended) — rejected: violates US1
scenario 4. `require_admin` — rejected by Q4 (reviewers/analysts need search). A non-`/clients`-scoped
search route — rejected: breaks the 4b `/clients/{id}/…` scoping convention and the isolation guarantee.

## D11 — No migration; no new app runtime dependency

**Decision**: **No Alembic migration.** Retrieval reads Spec 6's `chunks` (HNSW + GIN + `client_id`
indexes), `documents`, `document_sources`. The only new persisted-config is `Settings.
query_embedding_cache_ttl` (non-secret, `extra="forbid"` requires the field be declared). `hnsw.ef_search`
is set per-transaction at runtime (no DDL). Fusion is pure Python; the cache uses existing Redis; dense
queries use the `pgvector` dep added in Spec 6. So **no new app runtime dependency**; the only new
artifacts ship in the modelserver image (served by the already-present `onnxruntime`/`tokenizers`).

**Rationale**: Spec 6 deliberately built the index "hybrid-ready" (HNSW for dense, GIN for lexical),
precisely so the query half needs no schema change. Adding nothing to `_REQUIRED_SECRETS` and no
migration keeps the surface minimal.

**Alternatives considered**: A `chunks(client_id, embedder_version)` composite index to speed D8's
distinct-version scan — deferred (the per-client distinct scan is cheap; add only if profiling warrants).

## D12 — RAG eval gate (the first RAG gate; Principle IV)

**Decision**: Add a **`rag:`** block to `eval_thresholds.yaml`:
`rag: { hit_at_5: 0.85, mrr: 0.70, corroboration_accuracy: 1.0 }`. Commit **`eval/rag/golden_set.jsonl`**
(~15 cases: `{ "query", "relevant_document_keys": [...], "expected_corroboration_count": N }`, keyed by
stable `normalized_external_id` so the seed is reproducible). The **gate is an integration test**
`tests/integration/test_rag_eval.py`: it seeds a fixed corpus (the golden documents) for a throwaway
client, runs the real retrieval pipeline (embed → fuse → rerank), computes **hit@5, MRR, and
corroboration-count accuracy**, and **asserts each ≥ the committed threshold** (fails CI on regression).
It additionally asserts **hybrid+rerank ≥ dense-only** on hit@5/MRR (FR-026). A thin
`eval/rag/run_rag_eval.py` wraps the same scorer for manual/local runs and parity with the classifier
gate. CI runs this in the **integration test job** (Postgres+pgvector service + `uv sync --group
modelserver`). The gate boots the **modelserver ASGI app in-process** with `MODEL_DIR=modelserver/models`
and drives it through `httpx.ASGITransport` (the retrieval `ModelserverClient` base_url points at the
in-process app) — so real embeddings + rerank are exercised **without a separate modelserver container**.
Guarded by `skipif(find_spec("onnxruntime") is None)` (the Spec-6 modelserver-app-in-process pattern).

**Rationale**: A real RAG gate needs the DB index + embedder + reranker, so it belongs in the
integration job rather than the lean classifier `eval` job (which has no DB). Encoding it as a pytest
gives a NAMED failure and reuses the Spec-6 integration harness (fixtures, `session_factory`, modelserver
skip-guard). Faithfulness/answer-relevancy are **deferred** to the grounded-report/agent spec (no LLM
answer generation here) — recorded as a known boundary, not a gap.

**Alternatives considered**: Extending the lean `eval` job — rejected: it has no Postgres and is
deliberately torch/DB-free. A fully offline numpy-only retrieval eval (no DB) — rejected: would not
exercise the real HNSW/GIN/RRF/rerank path, so the number wouldn't protect production behavior.

## D13 — Determinism, resilience, and PII-safe logging

**Decision**: Determinism — fixed RRF `k`, `chunk.id` tie-break, single-thread ONNX rerank (the
modelserver embedder/classifier already pin `intra_op_num_threads=1`), `websearch_to_tsquery`/`<=>`
ordering with explicit `ORDER BY … , id`. Resilience — modelserver embed/rerank wrapped by the existing
tenacity retry (no 4xx retry); Redis cache failures are non-fatal (D7); empty corpus / no matches →
empty result + corroboration 0 (FR-015/SC-007). Logging — `structlog` bound to `client_id` and a
`query_hash` (sha256 prefix), **never** the raw query text or passage text, so patient identifiers /
pasted secrets cannot leak (FR-023; active Presidio redaction stays Spec 12). Metrics: per-stage counts
(dense/lexical candidates, fused, reranked, returned) + latency, no content.

**Rationale**: Stable orderings are required by the eval gate and by reproducible citations (a cited
passage must be retrievable again). PII-free logging matches the Spec-6 decision to store text
faithfully but never log it.

**Alternatives considered**: Logging truncated query text for debuggability — rejected: a query can
itself contain a pasted patient identifier; the `query_hash` gives correlation without exposure.

---

## Summary of new/changed surfaces

| Area | Change | New dep? | Migration? |
|------|--------|----------|------------|
| `app/rag/` package | NEW (schemas, query_embed, retrieval, fusion, rerank, corroboration, service, routes) | No | No |
| `modelserver` | `POST /rerank` + `inference/reranker.py` + 3 schemas + `main.py` wiring | No (onnxruntime present) | No |
| `modelserver/models/` | `reranker.onnx` + `reranker_tokenizer.json` + manifest entries (SHA-256 boot-validated) | — | No |
| `notebooks/` | `train_reranker.ipynb` (export/quantize) | `training` group only (dev) | No |
| `ModelserverClient` | `rerank()` + `rerank_chunked()` | No | No |
| `Settings` | `query_embedding_cache_ttl: int = 3600` | No | No |
| Eval | `eval/rag/golden_set.jsonl` + `run_rag_eval.py` + `eval_thresholds.yaml[rag]` + CI step | No | No |
| Redis | query-embedding cache (best-effort) | No (existing) | No |

No `_REQUIRED_SECRETS` change (the api already loads `modelserver_token`; retrieval calls the modelserver
the same way Spec 6's runner does). No `docker-compose` change (modelserver image rebuilds with the new
artifact; Postgres is already `pgvector/pgvector:pg16`).
</content>
