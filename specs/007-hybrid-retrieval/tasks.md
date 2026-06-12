---
description: "Task list for Spec 7 — Hybrid RAG Retrieval & Multi-Source Corroboration"
---

# Tasks: Hybrid RAG Retrieval & Multi-Source Corroboration

**Input**: Design documents from `specs/007-hybrid-retrieval/`

**Prerequisites**: plan.md, spec.md (user stories), research.md (D1–D13), data-model.md, contracts/ (6)

**Tests**: INCLUDED — the spec/plan define a unit+integration test plan and the constitution mandates
coverage gates (≥80% overall) plus the RAG eval gate (Principle IV).

> ⭐ **READ FIRST — `contracts/implementation-notes.md`.** It pins every existing API, exact import
> path, field name, and gotcha (verified against the live codebase) so there is nothing to guess. Each
> task assumes you have read it. Key traps it documents: use `get_acting_client` (not `_read`); the
> embedder sha comes from the `/embed` result (no `/ready` call); `documents` has `normalized_external_id`
> (not `external_id`) and `published_at` (not `date`); the cross-encoder needs pair encoding +
> `token_type_ids` (do NOT reuse `tokenize_batch`); `modelserver_url` is NOT a `Settings` field; CI has
> no modelserver container (boot it in-process via the `transport` seam).

**Organization**: grouped by user story (US1–US5) for independent implementation/testing. US2–US5
incrementally extend the US1 retrieval path (the `app/rag/service.py` orchestrator) but each remains
independently testable via its own tests.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no incomplete dependency)
- **[Story]**: US1–US5 (setup/foundational/polish carry no story label)

## Path Conventions

Web-service modular monolith: app code under `app/rag/`, modelserver under `modelserver/`, tests under
`tests/unit` and `tests/integration`, eval under `eval/rag/`. No migration (reads Spec-6 `chunks`).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: scaffolding and config that everything else builds on.

- [X] T001 Create the `app/rag/` package skeleton (`app/rag/__init__.py` with a one-sentence module docstring) and the `eval/rag/` directory, per plan.md Project Structure
- [X] T002 [P] Add the `rag:` threshold block (`hit_at_5: 0.85`, `mrr: 0.70`, `corroboration_accuracy: 1.0`) to `eval_thresholds.yaml`
- [X] T003 [P] Add `query_embedding_cache_ttl: int = 3600` to `Settings` in `app/core/config.py` (non-secret; respects `extra="forbid"`; NOT in `_REQUIRED_SECRETS`)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: the shared retrieval substrate every story needs.

**⚠️ CRITICAL**: no user-story work begins until this phase is complete.

- [X] T004 Define boundary schemas `RetrieveRequest`, `RetrievedPassage`, `CorroborationSource`, `RetrieveResponse` in `app/rag/schemas.py` per data-model.md (validation: query 1..1024 non-blank, top_k 1..50 default 10, optional filters)
- [X] T005 [P] Implement `normalize_query()` (NFKC→strip→lower→collapse-whitespace), `cache_key()`, and `query_hash()` in `app/rag/query_embed.py` per contracts/query-cache.md
- [X] T006 Implement embedder-version guard `assert_index_version(session, client_id, embedder_sha)` (DISTINCT `chunks.embedder_version`; raise `EmbedderVersionMismatch` on mismatch; empty set = OK) in `app/rag/query_embed.py` (FR-004/D8) — same file as T005
- [X] T007 Implement embedder-SHA memoization in `app/rag/query_embed.py`: read `model_version.sha256` from the first `/embed` result and memoize on `app.state.embedder_sha` (optionally seed from the empty-by-default `settings.embedder_model_version` pin). **No `app/core/lifespan.py` change, no `/ready` call, no boot coupling.** Consumed by US1's version guard (T006/T015) and the US5 cache key (T042) (D7/D8)
- [X] T008 Create `POST /clients/{client_id}/search` route skeleton in `app/rag/routes.py` with `Depends(get_acting_client)` (suspended refused, NO `require_admin`) and register `rag_router` in `app/main.py` (D10/FR-021)
- [X] T009 Create `app/rag/service.py` orchestrator skeleton `async def retrieve(session, redis, ms_client, client, req) -> RetrieveResponse` defining pipeline order and the empty-corpus short-circuit (`results=[]`, corroboration 0 — FR-015) — depends on T004

**Checkpoint**: schemas, endpoint, version guard, and orchestrator seam exist — stories can begin.

---

## Phase 3: User Story 1 - Retrieve grounded evidence passages (Priority: P1) 🎯 MVP

**Goal**: a staff user searches one client's corpus and gets a bounded, ranked list of the most
relevant passages — each with full provenance and a passage anchor — strictly client-scoped, with a
suspended client refused and an empty corpus returning empty.

**Independent Test**: seed one client's chunks; query; assert relevant passages returned with
source/section/reliability + anchor; assert zero foreign-client rows; suspended client refused; empty
corpus → empty + corroboration 0. (Dense/semantic ranking only at this stage.)

### Tests for User Story 1

- [X] T010 [P] [US1] Unit test query normalization + cache-key determinism in `tests/unit/test_query_cache_key.py`
- [X] T011 [P] [US1] Unit test embedder-version-mismatch refusal logic in `tests/unit/test_version_mismatch.py` (FR-004)
- [X] T012 [P] [US1] Integration test client isolation — zero foreign-client chunks in `tests/integration/test_retrieval_isolation.py` (SC-004/Principle V)
- [X] T013 [P] [US1] Integration test auth — suspended client refused (400), non-admin staff allowed in `tests/integration/test_retrieval_auth.py` (FR-021)
- [X] T014 [P] [US1] Integration test empty-corpus → `results: []` + corroboration 0 (no error) in `tests/integration/test_retrieval_empty_and_cache.py` (FR-015/SC-007)

### Implementation for User Story 1

- [X] T015 [US1] Implement `get_query_embedding()` (live `ModelserverClient.embed([q])`, no cache yet) and integrate `assert_index_version()` in `app/rag/query_embed.py` (FR-003/004) — after T005/T006
- [X] T016 [P] [US1] Implement `dense_candidates()` (client-scoped HNSW cosine `ORDER BY embedding <=> :qvec LIMIT n`, `SET LOCAL hnsw.ef_search=100`, optional chunk_type/reliability/date filters) in `app/rag/retrieval.py` (D2)
- [X] T017 [US1] Implement result projection (join `documents`/`document_sources` → `RetrievedPassage` with provenance + anchor) in `app/rag/retrieval.py` (FR-011/012/D9) — same file as T016
- [X] T018 [US1] Wire the dense-only path in `service.retrieve()`: version guard → embed → dense → project → top_k → `RetrieveResponse` (corroboration placeholder 0) (FR-001/009) — depends on T009/T015/T017
- [X] T019 [US1] Implement the route body in `app/rag/routes.py`: call service; map `EmbedderVersionMismatch`→409 `EMBEDDER_VERSION_MISMATCH`, `ModelserverError`→502; PII-free structured logging binding `client_id`+`query_hash` (FR-021/022/023)

**Checkpoint**: MVP — semantic search with citations, client-scoped, version-safe. Demoable.

---

## Phase 4: User Story 2 - Hybrid retrieval (Priority: P2)

**Goal**: fuse dense + lexical so exact-rare-term matches and paraphrase matches both surface; prove
hybrid ≥ dense-only on the golden set.

**Independent Test**: a lexical-only-match query and a semantic-only-match query both surface their
passage in the fused result; fused hit@k/MRR ≥ the better single leg.

### Tests for User Story 2

- [X] T020 [P] [US2] Unit test RRF fusion math + deterministic `id` tie-break in `tests/unit/test_rrf_fusion.py` (FR-007/010)
- [X] T021 [P] [US2] Integration test dense-only vs lexical-only vs fused; lexical-only & semantic-only both surface in `tests/integration/test_retrieval_hybrid.py` (US2)

### Implementation for User Story 2

- [X] T022 [US2] Implement `lexical_candidates()` (client-scoped `websearch_to_tsquery('english', :q)` + `ts_rank_cd`, same optional filters, `ORDER BY rank_score DESC, id ASC LIMIT n`) in `app/rag/retrieval.py` (D3) — same file as T016/T017
- [X] T023 [P] [US2] Implement `reciprocal_rank_fusion()` (k=60, sum 1/(k+rank), `id` tie-break, de-dup across legs) in `app/rag/fusion.py` (D1/FR-007/010)
- [X] T024 [US2] Extend `service.retrieve()` to run dense + lexical concurrently (`asyncio.gather`), fuse, then project the fused top candidates (replaces the dense-only path) (FR-007) — depends on T022/T023

**Checkpoint**: hybrid retrieval — both legs contribute; US1 tests still pass.

---

## Phase 5: User Story 3 - Multi-source corroboration (Priority: P2)

**Goal**: group retrieved passages by source document and report the corroboration count + ALL
distinct sources (never truncated).

**Independent Test**: seed N distinct documents reporting one event; query; assert
`corroboration_count == N` and all N sources listed with citation metadata; a multi-passage paper
counts once.

### Tests for User Story 3

- [X] T025 [P] [US3] Unit test corroboration grouping — N distinct docs; multi-passage→one source; never truncated in `tests/unit/test_corroboration.py` (FR-013/015)
- [X] T026 [P] [US3] Integration test corroboration count + all sources listed in `tests/integration/test_retrieval_corroboration.py` (US3/SC-003)

### Implementation for User Story 3

- [X] T027 [P] [US3] Implement `build_corroboration(passages)` (group by `document_id`; distinct count; `CorroborationSource` per doc with title/external_id/date/reliability/sources/`passage_chunk_ids`; never truncate) in `app/rag/corroboration.py` (D9/FR-013–015)
- [X] T028 [US3] Extend `service.retrieve()` to populate `corroboration_count` + `corroboration_sources` from the returned top-K (FR-014) — depends on T027

**Checkpoint**: corroboration surfaced over the cited top-K.

---

## Phase 6: User Story 4 - Reranking via cross-encoder on the modelserver (Priority: P3)

**Goal**: rerank the fused candidates with a cross-encoder (ONNX, served by the existing modelserver)
so the top-K is precise; prove rerank improves precision@k/MRR over fused-only.

**Independent Test**: modelserver `/rerank` returns scores in input order (batch ≤128, version-stamped,
token-auth); applying it reorders the fused top-K deterministically and improves the golden-set metric.

### Tests for User Story 4

- [X] T029 [P] [US4] Integration test modelserver `POST /rerank` contract (scores in input order, batch≤128, `model_version` stamp, `X-Service-Token`, 503 until ready) in `tests/integration/test_modelserver_rerank.py` (skip if `onnxruntime` absent, per Spec-6 pattern)
- [X] T030 [P] [US4] Integration test rerank reorders top-K deterministically in `tests/integration/test_retrieval_rerank.py` (US4/FR-008/010)

### Implementation for User Story 4 — modelserver

- [X] T031 [P] [US4] Offline notebook `notebooks/train_reranker.ipynb`: load `cross-encoder/ms-marco-MiniLM-L-6-v2`, export + INT8-quantize to ONNX → write `modelserver/models/reranker.onnx` + `reranker_tokenizer.json` (D4; Git LFS if >100MB)
- [X] T032 [P] [US4] Verify the dev-only `training` uv group in `pyproject.toml` already provides torch + transformers + accelerate + optimum[onnxruntime] (it does — confirmed) for the cross-encoder export; add `sentence-transformers` ONLY if the notebook loads via that API (optimum `ORTModelForSequenceClassification` does not need it). The serving `modelserver` group (onnxruntime + tokenizers) is unchanged
- [ ] T033 [US4] Add `reranker` + `reranker_tokenizer` entries (file/version/sha256/max_tokens) to `modelserver/models/manifest.json` (auto SHA-256-validated at boot by `validate_artifacts`) — after T031 runs
- [X] T034 [P] [US4] Implement `CrossEncoderSession` (tokenize (query,passage) pairs, ONNX run, relevance logit per passage; `intra_op_num_threads=1`; truncate 512) in `modelserver/inference/reranker.py` (D5)
- [X] T035 [P] [US4] Add `RerankRequest`, `RerankResult`, `RerankResponse` to `modelserver/schemas.py` (D5/data-model)
- [X] T036 [US4] Add `POST /rerank` (require_service_token, ready-gated, batch≤128, per-result version stamp, latency window key `rerank`) to `modelserver/routes.py` — depends on T034/T035
- [X] T037 [US4] Load `CrossEncoderSession` + reranker tokenizer into `app.state` at modelserver startup in `modelserver/main.py` — depends on T034

### Implementation for User Story 4 — app

- [X] T038 [P] [US4] Add `rerank()` + `rerank_chunked()` to `app/infra/modelserver_client.py` (mirror classify/embed; httpx+tenacity; no 4xx retry) (D6); **also add the optional `transport` seam** to `__init__`/`__aenter__` (production passes `None`; tests pass `httpx.ASGITransport`) per contracts/reranker-client.md
- [X] T039 [US4] Implement `app/rag/rerank.py` (call `rerank_chunked(query, [c.text…])`, zip scores by index, sort desc + `id` tie-break, take top_k) (D5/FR-008/010) — depends on T038
- [X] T040 [US4] Extend `service.retrieve()` to rerank the fused candidates (between fusion and projection) (FR-008) — depends on T039

**Checkpoint**: reranking improves the top-K; modelserver still boots healthy and <500MB.

---

## Phase 7: User Story 5 - Query-embedding cache (Priority: P3)

**Goal**: serve repeated query embeddings from Redis (best-effort); never fail on cache outage.

**Independent Test**: same query twice → second served from cache (no 2nd `/embed`); cache down → query
still succeeds via live embed; embedder-version change → stale entry not used.

### Tests for User Story 5

- [X] T041 [P] [US5] Integration test cache hit (no 2nd embed) + cache-down fallback in `tests/integration/test_retrieval_empty_and_cache.py` (the cache cases) (US5/SC-005)

### Implementation for User Story 5

- [X] T042 [US5] Add Redis GET/SET-with-TTL to `get_query_embedding()` in `app/rag/query_embed.py` (key = `rag:qemb:{embedder_sha}:{hash(norm_query)}`; best-effort try/except; version in key) (D7/FR-016–018) — extends T015
- [X] T043 [US5] Pass `app.state.redis` from the route into `service.retrieve()`; ensure cache failures are caught, logged (`rag.cache.unavailable`), and non-fatal in `app/rag/routes.py`/`service.py` (FR-018)

**Checkpoint**: repeated queries cached; cache strictly optional.

---

## Phase 8: Polish & Cross-Cutting Concerns (incl. the RAG eval GATE)

**Purpose**: the Principle-IV gate (depends on US2/US3/US4 existing) + docs + quality.

- [X] T044 [P] Build the committed RAG golden set (~15 cases: `query`, `relevant_document_keys` by `normalized_external_id`, `expected_corroboration_count`) in `eval/rag/golden_set.jsonl` (D12)
- [X] T045 Implement the shared scorer (hit@5, MRR, corroboration accuracy) + manual CLI in `eval/rag/run_rag_eval.py` vs `eval_thresholds.yaml[rag]` (D12) — depends on T044
- [X] T046 Implement the eval GATE `tests/integration/test_rag_eval.py`: boot the modelserver ASGI app in-process (`httpx.ASGITransport`, `MODEL_DIR=modelserver/models`; `skipif` onnxruntime absent), seed the golden corpus, run the pipeline → assert each metric ≥ threshold AND hybrid+rerank ≥ dense-only (FR-024–026/SC-001–003) — depends on T045 and US2/US3/US4
- [X] T047 Wire the RAG gate into CI: ensure the integration test job runs `uv sync --group modelserver` (onnxruntime + `modelserver/models` on disk) so `test_rag_eval.py` drives the in-process modelserver app — no separate modelserver container required — in `.github/workflows/ci.yml` (D12)
- [ ] T048 [P] Update `docs/RUNBOOK.md`: search endpoint usage, reranker artifact rebuild + `/ready` check, RAG eval run, <500MB image-budget check
- [ ] T049 [P] Lint/hygiene pass — `ruff check` + `black --check` on `app/rag`, `modelserver`, `tests`; files ≤300 lines; one-sentence module docstrings; PII-free logs verified
- [ ] T050 Run `quickstart.md` end-to-end on the live stack (search · hybrid · corroboration · isolation · cache · version-mismatch · empty) and confirm coverage ≥80%; **spot-check SC-006** (warm-cache median retrieval latency < 1 s for default top-K) via the per-stage latency logs — observed, not gated

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (P1)** → no deps.
- **Foundational (P2)** → after Setup; **blocks all stories**.
- **US1 (P3)** → after Foundational. MVP.
- **US2 (P4)** → after US1 (extends `service.retrieve()` dense path into hybrid; reuses retrieval.py).
- **US3 (P5)** → after US1 (groups the returned top-K). Independent of US2's fusion but naturally follows it.
- **US4 (P6)** → after US2 (reranks the *fused* candidates). The modelserver subtasks (T031–T037) are independent of the app subtasks until T040 wires them.
- **US5 (P7)** → after US1 (extends the embed step). Independent of US2–US4.
- **Polish/eval gate (P8)** → after US2+US3+US4 (the gate proves hybrid≥dense, corroboration accuracy, and rerank).

### Within each story

- Tests first (write to fail), then implementation; models/schemas before services; services before the route wiring.
- `app/rag/service.py` is the shared orchestrator extended by US1→US2→US3→US4→US5 — those `service.retrieve()` edits are sequential even though each story is independently testable via its own tests.

### Parallel opportunities

- Setup: T002, T003 in parallel.
- Foundational: T004 (schemas) parallel with T008/T009 wiring; **T005/T006/T007 all touch `app/rag/query_embed.py` → sequential** (T005 helpers → T006 version guard → T007 sha memoization).
- US1 tests T010–T014 all parallel; T016 parallel with T015 (different files).
- US4 modelserver: T031, T032, T034, T035, T038 parallel (different files); T033→after T031; T036→after T034/T035; T037→after T034; T039→after T038; T040 last.
- Polish: T044, T048, T049 parallel.

---

## Parallel Example: User Story 1 tests

```bash
# Launch US1 tests together (all different files):
Task: "Unit test query normalization + cache-key in tests/unit/test_query_cache_key.py"
Task: "Unit test version-mismatch refusal in tests/unit/test_version_mismatch.py"
Task: "Integration test isolation in tests/integration/test_retrieval_isolation.py"
Task: "Integration test auth in tests/integration/test_retrieval_auth.py"
Task: "Integration test empty-corpus in tests/integration/test_retrieval_empty_and_cache.py"
```

---

## Implementation Strategy

### MVP first (US1 only)

1. Phase 1 Setup → 2. Phase 2 Foundational → 3. Phase 3 US1 → **STOP & VALIDATE**: client-scoped
   semantic search with citations, version-safe, isolated. Demoable.

### Incremental delivery (PR-sized slices, <400 lines each)

1. Setup + Foundational + US1 (MVP) → demo.
2. US2 hybrid fusion → demo (hybrid recall).
3. US3 corroboration → demo (N sources).
4. US4 reranking (modelserver `/rerank` + artifact as one PR; app rerank wiring as another) → demo.
5. US5 query cache → demo (latency).
6. Polish + RAG eval gate → CI green, thresholds committed.

### Notes

- No Alembic migration (reads Spec-6 `chunks`); no new container (rerank on the existing modelserver);
  no new app runtime dep (fusion pure Python; pgvector + Redis already present); no `_REQUIRED_SECRETS`
  change.
- The reranker artifact must keep the modelserver image <500MB (quantize; `ms-marco-MiniLM-L-2-v2`
  fallback) — Constitution VI.
- Commit per task/logical group (Conventional Commits, no Co-Authored-By trailer).
</content>
