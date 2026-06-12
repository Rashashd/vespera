# Implementation Plan: Hybrid RAG Retrieval & Multi-Source Corroboration

**Branch**: `007-hybrid-retrieval` | **Date**: 2026-06-11 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/007-hybrid-retrieval/spec.md`

## Summary

Build the **query** half of Pantera's RAG pipeline on top of Spec 6's chunk index. Given a
natural-language query for one client, the system: (1) **embeds the query** via the existing medical
ONNX embedder (`ModelserverClient.embed`), serving repeats from a **Redis query-embedding cache** and
**refusing** the query if the live embedder version ≠ the client's stored `chunks.embedder_version`
(FR-004, fail-fast — never score against incomparable vectors); (2) runs **dense** retrieval over the
existing HNSW `vector_cosine_ops` index and **lexical** retrieval over the existing GIN `text_tsv`
index, both `client_id`-scoped; (3) **fuses** the two candidate lists with **Reciprocal Rank Fusion**;
(4) **reranks** the fused top candidates with a **cross-encoder exported to ONNX and served by the
existing modelserver** via a new `POST /rerank` endpoint (no torch at serve time, no new service); and
(5) projects the top-K into validated results carrying full **provenance + a passage anchor**, then
**groups by source document** to report a **corroboration count and ALL sources** (Principle II).

Retrieval is exposed as a reusable in-app capability and as a staff-facing endpoint
`POST /clients/{client_id}/search` (per-request `acting_client` authorization; suspended client
refused; any staff role with access — not admin-only). Quality is gated by the project's **first RAG
eval**: a committed ~15-case golden set scored for **hit@5 ≥ 0.85, MRR ≥ 0.70, and 100%
corroboration-count accuracy**, with hybrid+rerank proven to beat a dense-only baseline (Principle IV).

This spec adds **no Alembic migration** (it reads Spec 6's tables), **no new container** (rerank rides
the existing modelserver), and **no new app runtime dependency** (`pgvector` already present; fusion is
pure Python; the cache uses the existing Redis). It adds: a new in-app `app/rag/` package; a modelserver
`/rerank` endpoint + a fourth model artifact (`reranker.onnx` + its tokenizer) trained/exported offline;
`rerank()` on `ModelserverClient`; one non-secret `Settings` field (cache TTL); and the `rag:` eval
block + golden set + CI step. Report drafting, grounded LLM summarization, severity/NER, the LangGraph
`retrieve` tool wrapper, HITL, and NeMo Guardrails are explicitly **out of scope** (Specs 8/9/11/12).

## Technical Context

**Language/Version**: Python 3.13 (managed by `uv`). Modelserver shares the runtime but a separate lean
uv group (`modelserver`: onnxruntime + tokenizers + numpy, no torch).

**Primary Dependencies**:
- *Existing (reused)*: FastAPI, SQLAlchemy 2 async + asyncpg, Pydantic v2, **pgvector** (`Vector(768)`
  column + cosine operators, added in Spec 6), `redis.asyncio` (`app/infra/redis.py`), structlog,
  `app/infra/modelserver_client.py` (httpx + tenacity), `app/auth` guards (`acting_client`), the
  domain-event dispatcher, the modelserver (`onnxruntime`, `tokenizers`, manifest SHA-256 validation).
- *New model artifact (offline-trained, no new runtime dep)*: a **cross-encoder reranker exported to
  ONNX** (e.g. `cross-encoder/ms-marco-MiniLM-L-6-v2`), quantized and committed under
  `modelserver/models/`, served by the existing modelserver via `onnxruntime` (already in the
  `modelserver` group). Its export uses the **dev-only `training` uv group** (torch/transformers),
  exactly like the classifier/embedder.
- *No new app runtime dependency.* RRF is pure Python; dense/lexical queries use pgvector + Postgres
  full-text already available; the query cache uses the existing Redis client.

**Storage**: PostgreSQL (+ pgvector). **No migration** — retrieval reads Spec 6's `chunks`
(HNSW `ix_chunks_embedding_hnsw` `vector_cosine_ops`, GIN `ix_chunks_text_tsv`, `client_id` index),
joins `documents`/`document_sources` for citation metadata. Redis holds transient query-embedding cache
entries (TTL-bounded, best-effort). The reranker artifact is committed to `modelserver/models/`
(Git LFS if > 100 MB; quantize to stay within the < 500 MB image budget — Principle VI).

**Testing**: `uv run pytest`. **Unit**: RRF fusion (rank math, deterministic tie-break); query
normalization + cache key; corroboration grouping (N distinct docs, multi-passage single-source count,
no truncation); version-mismatch refusal logic; result projection/anchor shape. **Integration** (live
stack, `PANTERA_INTEGRATION=1`, Postgres+pgvector + modelserver): dense-only vs lexical-only vs fused
recall; lexical-only-match and semantic-only-match both surface in fused; rerank reorders top-K;
client isolation (zero foreign chunks); empty-corpus → empty result + corroboration 0; cache hit (no
2nd embed) + cache-down fallback; version-mismatch → refused; auth (suspended client refused;
non-admin staff allowed). **Eval gate**: `tests/integration/test_rag_eval.py` seeds the committed
golden corpus, scores hit@5/MRR/corroboration accuracy against `eval_thresholds.yaml[rag]`, and fails
CI on regression; a thin `eval/rag/run_rag_eval.py` wraps the same scorer for manual runs. Modelserver
`/rerank` contract tests run in the lean `modelserver`-group env (skip when onnxruntime absent, like
Spec 6).

**Target Platform**: Linux containers in the docker-compose modular monolith — the `api` service hosts
`app/rag/`; the `modelserver` service gains `/rerank`. The retrieval service layer is written
framework-agnostically (session + redis + modelserver client injected) so Spec 9's LangGraph
`retrieve` tool and Spec 11's worker reuse it unchanged.

**Performance Goals**: Median retrieval latency < 1 s for the default top-K on a warm cache (SC-006).
HNSW gives sub-linear dense search; lexical uses the GIN index; rerank is bounded to the fused
candidate pool (≤ 50). The query-embedding cache removes the embed round-trip on repeats.

**Constraints**: Async throughout (no `requests`/`time.sleep`); tenacity retries on modelserver calls,
never on 4xx; **client isolation absolute** (every query `client_id`-scoped, verified by test —
Principle V); **no torch in any serving container** and modelserver image < 500 MB (Principle VI);
fusion + rerank **deterministic** for stable evals and reproducible citations (FR-010); structured,
**PII-free** logs binding `client_id` (never log raw query/passage text in a way that exposes PII);
files ≤ ~300 lines with a one-sentence docstring; ruff **and** black clean; coverage ≥ 80% overall.

**Scale/Scope**: Moderate per-client corpora (hundreds–thousands of chunks). One new in-app package
(~8 files); one new modelserver endpoint + inference module + 3 schemas; one offline reranker artifact
+ training notebook; one `ModelserverClient` method; one `Settings` field; one eval golden set + scorer
+ `eval_thresholds.yaml` block + CI step. **No migration, no new container, no new app runtime dep.**

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Relevance | Status |
|-----------|-----------|--------|
| I. Human-in-the-Loop | Retrieval is read-only decision-support input; no drafting/sending, no autonomous determination. | ✅ N/A |
| II. Grounding (NON-NEGOTIABLE) | **Core enabler**: returns the citable passages + anchors reports ground on; **corroboration** surfaces ALL N sources, never a truncated subset (FR-013–FR-015); FR-004 refuses version-mismatched (incomparable-vector) retrieval rather than return silently-wrong evidence. | ✅ Enabling/Protective |
| III. Triage Fails Safe | Hybrid+rerank maximizes recall of the right evidence so downstream triage sees the full picture; retrieval includes all client chunks incl. eventual-irrelevant (cross-document context). | ✅ Enabling |
| IV. Backed by a Number (NON-NEGOTIABLE) | Adds the project's **first RAG eval gate**: golden set with committed hit@5/MRR/corroboration thresholds in `eval_thresholds.yaml`; hybrid+rerank proven to beat dense-only (FR-024–FR-026, SC-001/002/003). | ✅ Gate added |
| V. Multi-Tenant Isolation (NON-NEGOTIABLE) | Every dense/lexical query filtered by `client_id`; results provably single-client (SC-004); endpoint uses per-request server-validated `acting_client` (suspended client refused); no read crosses clients. | ✅ Enforced |
| VI. Lean, Reproducible, Justified | **No new container** (rerank on existing modelserver), **no torch at serve** (cross-encoder→ONNX, validated by SHA-256 like other artifacts, image < 500 MB), **no MCP**, **no new app runtime dep**; reranker trained offline in `training` group; `uv` lockfile. | ✅ Aligned |
| VII. Own Every Line (Spec-Driven) | spec → clarify → plan → tasks → implement; Conventional Commits; PRs < 400 lines (PR-able slices: modelserver /rerank + artifact; app/rag dense+lexical+fusion; rerank+corroboration+endpoint; query cache; eval gate + golden set); files ≤ 300 lines. | ✅ Aligned |

**Security & standards applied**: endpoint requires per-request `acting_client(client_id)` (server-
validated target client, suspended refused, audit-attributable — Constitution V controls a/b); query
and passage text **stored/returned faithfully but never logged** with PII (PII-free `structlog`,
binding `client_id`; active Presidio redaction remains Spec 12); modelserver `/rerank` requires the
existing `X-Service-Token`; the reranker artifact is **SHA-256-validated at modelserver startup**
(reuses `validate_artifacts`, which iterates all manifest entries — adding the artifact auto-enrolls
it); modelserver calls use the existing tenacity policy (no retry on 4xx).

**Result**: PASS — no violations. Complexity Tracking intentionally empty: no new container (rerank
reuses the modelserver), no new external service, no torch at serve time, no migration, no new app
runtime dependency. The one new model artifact maps directly to the required reranking capability and
is justified as the project's stated "one justified RAG improvement" (Brief §5-D).

## Project Structure

### Documentation (this feature)

```text
specs/007-hybrid-retrieval/
├── plan.md              # This file
├── research.md          # Phase 0 output (decisions D1–D13)
├── data-model.md        # Phase 1 output (no tables; read projections, cache key, golden-set + manifest artifact)
├── quickstart.md        # Phase 1 output (run/validate guide)
├── contracts/           # Phase 1 output
│   ├── implementation-notes.md # ⭐ READ FIRST — codebase-grounded exact APIs/signatures/gotchas (anti-hallucination)
│   ├── search-endpoint.md     # POST /clients/{id}/search — request/response, auth, errors
│   ├── retrieval-pipeline.md  # dense + lexical query shape, RRF fusion, determinism contract
│   ├── modelserver-rerank.md  # POST /rerank request/response + artifact/manifest/startup contract
│   ├── reranker-client.md      # ModelserverClient.rerank()/rerank_chunked() contract
│   ├── query-cache.md          # Redis query-embedding cache key/TTL/fallback + version check (FR-004)
│   └── rag-eval-gate.md        # golden-set format, metrics, eval_thresholds.yaml[rag], CI wiring
├── checklists/
│   └── requirements.md         # spec-quality gate (from /speckit-specify, all green)
└── tasks.md             # /speckit-tasks output (NOT created here)
```

### Source Code (repository root)

A new in-app **`app/rag/`** package (mirroring `app/embedding/`), modelserver `/rerank` additions, one
`ModelserverClient` method, one `Settings` field, the eval golden set + scorer + threshold block + CI
step, and router registration in `app/main.py`. No existing schema changes; no migration.

```text
app/rag/                               # NEW in-app domain package (the query half of RAG)
├── __init__.py
├── schemas.py                         # Pydantic: RetrieveRequest, RetrievedPassage, CorroborationSource, RetrieveResponse
├── query_embed.py                     # query normalize + Redis cache (get/set, TTL) + embedder-version check (FR-004/016/017)
├── retrieval.py                       # client-scoped dense (HNSW cosine) + lexical (tsquery/ts_rank) candidate queries
├── fusion.py                          # Reciprocal Rank Fusion (deterministic tie-break) (FR-007/010)
├── rerank.py                          # call modelserver /rerank over fused candidates; reorder top-K (FR-008)
├── corroboration.py                   # group passages by document; count distinct sources; list ALL (FR-013–015)
├── service.py                         # orchestration: embed→dense+lexical(gather)→fuse→rerank→project+corroborate
└── routes.py                          # POST /clients/{id}/search (acting_client; suspended refused; any staff w/ access)

modelserver/                           # rerank rides the EXISTING lean container (no new service)
├── inference/reranker.py              # NEW: CrossEncoderSession — (query, passages) → scores via ONNX (no torch)
├── routes.py                          # ADD: POST /rerank (X-Service-Token, batch ≤128, version-stamped)
├── schemas.py                         # ADD: RerankRequest, RerankResult, RerankResponse
├── main.py                            # ADD: load reranker session + tokenizer into app.state
└── models/
    ├── reranker.onnx                  # NEW committed artifact (quantized; Git LFS if >100MB)
    ├── reranker_tokenizer.json        # NEW reranker tokenizer (cross-encoder wordpiece)
    └── manifest.json                  # ADD reranker + reranker_tokenizer entries (auto SHA-256-validated at boot)

notebooks/
└── train_reranker.ipynb              # NEW offline: load cross-encoder → export+quantize ONNX → write manifest sha256 (training group)

app/infra/modelserver_client.py        # ADD: rerank() + rerank_chunked() (mirror classify/embed; httpx+tenacity)
app/core/config.py                     # ADD: query_embedding_cache_ttl: int = 3600 (non-secret; extra="forbid")
app/main.py                            # ADD: include_router(rag_router)

eval/rag/                              # NEW RAG eval (parallels modelserver/eval)
├── golden_set.jsonl                   # ~15 committed query→relevant-doc(+corroboration) cases
└── run_rag_eval.py                    # manual scorer (hit@5/MRR/corroboration) vs eval_thresholds.yaml[rag]
eval_thresholds.yaml                   # ADD rag: {hit_at_5: 0.85, mrr: 0.70, corroboration_accuracy: 1.0}
.github/workflows/ci.yml               # ADD: RAG eval runs in the integration test job (has Postgres+pgvector)

tests/
├── unit/
│   ├── test_rrf_fusion.py             # rank fusion math + deterministic tie-break (FR-007/010)
│   ├── test_query_cache_key.py        # normalization + key = f(embedder_sha, norm_query); TTL; version scoping
│   ├── test_corroboration.py          # N distinct docs; multi-passage→one source; never truncated (FR-013–015)
│   └── test_version_mismatch.py       # current embedder sha vs client chunk versions → refuse (FR-004)
└── integration/
    ├── test_retrieval_hybrid.py       # dense-only/lexical-only/fused; lexical-only & semantic-only both surface (US2)
    ├── test_retrieval_rerank.py       # rerank reorders top-K; deterministic (US4)
    ├── test_retrieval_isolation.py    # zero foreign-client chunks (SC-004, Principle V)
    ├── test_retrieval_corroboration.py# N sources reported + all listed (US3, SC-003)
    ├── test_retrieval_empty_and_cache.py # empty corpus → empty/0; cache hit (no 2nd embed); cache-down fallback
    ├── test_retrieval_auth.py         # suspended client refused; non-admin staff allowed (FR-021)
    ├── test_modelserver_rerank.py     # /rerank contract: scores, order, batch≤128, version stamp, auth (skip if no onnxruntime)
    └── test_rag_eval.py               # GATE: seed golden corpus → score → assert ≥ eval_thresholds.yaml[rag]
```

**Structure Decision**: Build the query half as an in-app **`app/rag/`** package that mirrors the
proven `app/embedding/` shape (schemas, focused single-responsibility modules, a `service.py`
orchestrator, `routes.py`), because retrieval is core business logic over the platform's own data and
the only no-torch concern (the cross-encoder) is isolated in the existing modelserver — exactly the
boundary Spec 5/6 established. The cross-encoder is served by the **existing modelserver** rather than a
new "reranker service" (Constitution VI; the Brief's separate-reranker mention is folded into the
no-torch inference container). The retrieval `service.py` takes its session, Redis, and modelserver
client by injection so Spec 9's LangGraph `retrieve` tool and Spec 11's worker reuse it unchanged. No
migration is needed because Spec 6 already shipped the dense (HNSW) and lexical (GIN) indexes this spec
queries.

## Complexity Tracking

> No constitution violations — table intentionally empty. The feature adds **no** new container
> (reranking reuses the existing modelserver), **no** migration (reads Spec 6's indexes), and **no**
> new app runtime dependency (fusion is pure Python; pgvector and Redis are already present). The one
> new model artifact (cross-encoder → ONNX) maps directly to the required, eval-proven reranking
> capability and is the Brief's designated "one justified RAG improvement," trained offline in the
> dev-only `training` group and served no-torch within the < 500 MB image budget.
</content>
