# Implementation Notes — Anti-Hallucination Reference (Spec 7)

**Read this before writing any code.** Every fact below was verified against the live codebase on
2026-06-11. Use these **exact** names, signatures, and import paths. Where a "gotcha" is marked ⚠️, the
obvious guess is wrong. Do NOT invent APIs, fields, or settings not listed here.

---

## 1. Existing APIs to reuse (exact import paths & signatures)

### Auth / dependencies (`app/auth/dependencies.py`)
- `from app.auth.dependencies import get_acting_client` → a `Depends`-able that takes the `client_id`
  **path param** and returns a `app.clients.models.Client`. **Refuses a suspended client with `400`
  `CLIENT_SUSPENDED`**; `404 CLIENT_NOT_FOUND` if absent/not the caller's; recomputes from stored state.
  **Use this for `POST /clients/{client_id}/search`.**
- ⚠️ Do **NOT** use `get_acting_client_read` (it sets `allow_suspended=True` → would let a suspended
  client be queried, violating US1 scenario 4).
- ⚠️ Do **NOT** add `require_admin` to the search route (Q4: any staff role with access).
- `from app.core.dependencies import get_session` → yields an `AsyncSession` from
  `request.app.state.session_factory`.

### Client model (`app/clients/models.py`)
- `Client.status` is a **string**; active = `"active"`. "Suspended" means `status != "active"` (handled
  by `get_acting_client`; you do not re-check it).

### App state (set in `app/core/lifespan.py`)
Available on `request.app.state`: `settings`, `engine`, `session_factory`, `redis`, `llm`, `dispatcher`,
`limiter`. **There is no `app.state.modelserver_client`** — build one per request (see §3).
- ⚠️ `app.state.embedder_sha` does **not exist yet** — T007 creates it (memoized from the first `/embed`).

### Route pattern to MIRROR (`app/embedding/routes.py`)
- Get deps via `request.app.state.session_factory` / `.settings`.
- `router = APIRouter(prefix="/clients/{client_id}", tags=["rag"])`; register in `app/main.py` with
  `app.include_router(rag_router)` (add the import + one line, mirroring the `embedding_router` line).
- **Difference from Spec 6:** the index trigger runs work in `BackgroundTasks`; **retrieval runs inline**
  (synchronous request→response) and returns the `RetrieveResponse`.

### ModelserverClient (`app/infra/modelserver_client.py`)
- `from app.infra.modelserver_client import ModelserverClient, ModelserverError`.
- Use as: `async with ModelserverClient.from_settings(settings) as client: …` (it asserts `_http` is set;
  must be entered).
- `from_settings(settings)` → `base_url = getattr(settings, "modelserver_url", "http://modelserver:8001")`,
  `token = settings.modelserver_token`. ⚠️ **`modelserver_url` is NOT a `Settings` field — do not add it**;
  the `getattr` default is intentional.
- `await client.embed(texts: list[str]) -> list[dict]` → returns `resp["results"]`; each item is
  `{"embedding": [768 floats], "model_version": {"name": str, "version": str, "sha256": str}}`. ⚠️ It is
  a **list of dicts** (dict access, not attributes); the top-level dim/max_tokens live on the response,
  not each result.
- `await client.embed_chunked(texts)` → same, batched ≤128.
- **NEW (you add):** `rerank(query, passages) -> list[dict]` / `rerank_chunked(query, passages)` →
  each `{"score": float, "model_version": {…}}`, input order. See `contracts/reranker-client.md`.
- Retries: `_post_with_retry` uses `app/infra/http.py::with_retry` (3 attempts, exp backoff, **never
  4xx**); non-2xx after retries → raises `ModelserverError`. Map `ModelserverError` → HTTP `502` in the route.

### HTTP infra (`app/infra/http.py`)
- `build_http_client()` → configured `httpx.AsyncClient`. `with_retry` decorator already applied inside
  `ModelserverClient`. You do not re-implement retries.

### Redis (`app/infra/redis.py` → `app.state.redis`)
- It is a `redis.asyncio.Redis` created with **`decode_responses=True`** → `await redis.get(key)` returns
  a **`str`** (or `None`), not bytes. `await redis.set(key, json_str, ex=ttl_seconds)`.

---

## 2. Data the retrieval reads (exact columns — `app/embedding/models.py`, `app/ingestion/models.py`)

### `Chunk` (`app/embedding/models.py::Chunk`, table `chunks`)
Columns: `id, client_id, document_id, ordinal, chunk_type (str), section (str|None), drug (str|None,
NULL in v1 — do not filter on it), date (datetime|None), source_reliability (str), text (str),
embedding (Vector(768)), text_tsv (TSVECTOR, GENERATED), embedder_version (str, sha256, len 64),
created_at`.
- **Dense query (SQLAlchemy + pgvector):** `Chunk.embedding.cosine_distance(qvec)` gives the `<=>`
  distance; `.order_by(Chunk.embedding.cosine_distance(qvec)).limit(n)`. `qvec` is a `list[float]` of 768.
- **Set HNSW recall:** `await session.execute(text("SET LOCAL hnsw.ef_search = 100"))` inside the txn.
- **Lexical query:** `q = func.websearch_to_tsquery('english', query_str)`; filter
  `Chunk.text_tsv.op("@@")(q)`; rank `func.ts_rank_cd(Chunk.text_tsv, q)` ordered desc, then `Chunk.id`.
  ⚠️ The text-search config **must be `'english'`** (matches the Spec-6 generated `text_tsv`); a different
  config silently bypasses the GIN index.
- Indexes already present (no DDL): `ix_chunks_client_id`, `ix_chunks_embedding_hnsw`
  (`vector_cosine_ops`), `ix_chunks_text_tsv` (GIN), `ix_chunks_client_chunk_type`.

### `Document` (`app/ingestion/models.py::Document`, table `documents`)
- Provenance columns: `id, client_id, normalized_external_id (str), source_reliability (str),
  title (str|None), published_at (datetime|None)`.
- ⚠️ There is **no `external_id`** column — use **`normalized_external_id`** for the citation `external_id`.
- ⚠️ Publication date is **`published_at`** (not `date`); map it to the result/chunk `date`.
- Relationship `Document.sources` (lazy `selectin`) → `list[DocumentSource]`; each `DocumentSource.source`
  is the feed name (one of `pubmed, europepmc, openfda_faers, openfda_label, fda_medwatch, ema, mhra`).
  Use these for the result's `sources` list.

### Enums
- `from app.embedding.enums import ChunkType` (`text, table, figure_caption, structured_data`).
- `from app.ingestion.enums import SourceReliability` (`regulatory_alert, peer_reviewed, preprint,
  case_report`; has `.rank`). Use the StrEnum **values** in filters.

---

## 3. Settings (`app/core/config.py`) — what to add and what already exists

- **ADD exactly one field:** `query_embedding_cache_ttl: int = 3600`. `Settings` has
  `extra="forbid"`, so the field must be declared. Non-secret; **not** in `_REQUIRED_SECRETS`; **not** in
  the Vault writer; no `startup.py` change.
- ⚠️ `embedder_model_version: str = ""` **already exists** but is **empty by default** — it is declared in
  `Settings` yet **NOT loaded in `app/core/startup.py`** (only `database_url, redis_url,
  anthropic_api_key, openai_api_key, modelserver_token, guardrails_token, auth_jwt_secret, bootstrap_*`
  are). Treat it as an OPTIONAL pin; the real embedder sha comes from the `/embed` result (§4).
- ⚠️ Do **NOT** add `modelserver_url`, do **NOT** add anything to `_REQUIRED_SECRETS`, do **NOT** touch
  the Vault inline writer in `ci.yml` (the api already has `modelserver_token`).

---

## 4. Embedder-version handling (no `/ready`, no boot coupling)

- The current embedder sha = `embed_result[0]["model_version"]["sha256"]` (every `/embed` returns it —
  this is exactly how `app/embedding/runner.py` reads versions in Spec 6).
- Memoize it on `app.state.embedder_sha` after the first embed (optionally seed from the empty-by-default
  `settings.embedder_model_version`). Used for the cache key (before embed, when memo is warm) and the
  version guard.
- Guard (FR-004): `SELECT DISTINCT embedder_version FROM chunks WHERE client_id = :cid`. Empty → OK
  (empty result). `== {current_sha}` → OK. Else → raise `EmbedderVersionMismatch` → route returns
  **`409` `EMBEDDER_VERSION_MISMATCH`**.

---

## 5. Modelserver `/rerank` additions (mirror `/embed`)

### `modelserver/main.py` lifespan (`_lifespan`)
Add after the embedder block, mirroring it exactly:
```python
rr_tok_entry = manifest.artifact("reranker_tokenizer")
reranker_tokenizer = load_tokenizer(str(model_dir / rr_tok_entry["file"]))
rr_entry = manifest.artifact("reranker")
from modelserver.inference.reranker import CrossEncoderSession
app.state.reranker = CrossEncoderSession(model_dir / rr_entry["file"],
                                         tokenizer=reranker_tokenizer, max_tokens=config.max_tokens)
app.state.model_versions["reranker"] = {"version": rr_entry["version"], "sha256": rr_entry["sha256"],
                                         "format": rr_entry["format"]}
```
- ⚠️ `validate_artifacts(model_dir, manifest.raw)` already iterates **all** manifest artifacts → adding
  the two manifest entries auto-enrolls them in SHA-256 boot validation. **No change to
  `modelserver/core/startup.py`.**

### `modelserver/routes.py` — `POST /rerank`
Mirror the `embed` handler: `dependencies=[Depends(require_service_token)]`, `response_model=RerankResponse`;
guard `if not getattr(request.app.state, "ready", False): raise HTTPException(503, "Service not ready")`;
time it and `_record_latency("rerank", latency_ms)`; `mv = ModelVersion(**request.app.state.manifest.model_version("reranker"))`.
- `require_service_token` (`modelserver/core/auth.py`): missing `X-Service-Token` → `401`; wrong → `403`;
  no `app.state.service_token` → `503`.

### `modelserver/schemas.py` — add (mirror `EmbedRequest`/`EmbedResponse`)
`RerankRequest{ query: str; passages: list[str] = Field(max_length=128) }`;
`RerankResult{ score: float; model_version: ModelVersion }`;
`RerankResponse{ model_version: ModelVersion; results: list[RerankResult] }`.

### `modelserver/inference/reranker.py`
See `contracts/modelserver-rerank.md` — **pair-encode with `token_type_ids`** (do NOT reuse
`tokenize_batch`); output `logits[:, 0]`; `intra_op_num_threads=1`, `CPUExecutionProvider`.

### Config facts (`modelserver/core/config.py`)
`model_dir = Path("modelserver/models")`, `max_tokens = 512`, `max_batch = 128`. Boot is
`load token → validate_artifacts → load sessions → app.state.ready = True`.

---

## 6. Artifacts & uv groups

- Commit `modelserver/models/reranker.onnx` + `reranker_tokenizer.json`; append both to
  `modelserver/models/manifest.json` (shape: `{name, file, format, version, sha256[, max_tokens]}`,
  matching the existing `embedder`/`tokenizer` entries). Git LFS if a file > 100 MB; quantize to keep the
  image < 500 MB.
- ⚠️ The dev-only `training` uv group **already** has `torch`, `transformers`, `accelerate`,
  `optimum[onnxruntime]` — sufficient to export the cross-encoder. The serving `modelserver` group already
  has `onnxruntime` + `tokenizers`. No serve-time dependency is added.

---

## 7. CI & tests (`.github/workflows/ci.yml`)

- The integration **test job** runs `uv sync --group modelserver`, then `docker compose up -d --wait
  vault postgres redis` (⚠️ **no modelserver container**), writes secrets into Vault (incl.
  `modelserver_token = "ci-test-token"`), `alembic upgrade head`, then `pytest` with
  `PANTERA_INTEGRATION=1` and the 80% coverage gate. DB/Redis URLs come from **Vault**, not env.
- The lean **`eval` job** runs only `modelserver/eval/run_eval.py` (classifier) — leave it unchanged.
- Therefore the RAG eval + rerank integration tests **boot the modelserver ASGI app in-process** via the
  `transport` seam (§ `contracts/reranker-client.md`), `MODEL_DIR=modelserver/models`, set the service
  token to match, and `skipif(find_spec("onnxruntime") is None)`. No new CI service container.
- Test patterns to reuse from Spec 6: `tests/integration` fixtures (`make_client`, `make_document`,
  `make_watchlist`), real `session_factory` (not a shared session), async `select()` (not `.query()`),
  structlog `LogCapture` for PII-log assertions, `skipif onnxruntime` for modelserver-app tests. On this
  Windows host see `memory/host-integration-test-vault-repoint.md` (5433/6380 + Vault repoint).

---

## 8. Hard rules (Constitution) for every file you write

- Every route/tool/external call is `async`; never `requests`/`time.sleep`. Parallel I/O via
  `asyncio.gather` (run dense + lexical concurrently).
- Each new file opens with a **one-sentence module docstring**; keep files **≤ ~300 lines** (split if
  larger).
- **PII-free logs:** bind `client_id` + `query_hash` (sha256 prefix of the normalized query); **never**
  log raw query text or passage text.
- API routes return **validated Pydantic models**, never ORM objects.
- Every dense/lexical query has `WHERE client_id = :cid` — no unscoped chunk query exists anywhere.
- `ruff check` **and** `black --check` must both pass on `app worker tests` (and `modelserver`).
- Conventional Commits; **no `Co-Authored-By` trailer**; PRs < 400 lines.
</content>
