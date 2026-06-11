# Implementation Plan: Parse, Chunk & Embed — RAG Index Build

**Branch**: `006-parse-chunk-embed` | **Date**: 2026-06-10 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/006-parse-chunk-embed/spec.md`

## Summary

Turn the stored corpus (Spec 4 `documents` + per-source `document_sources.raw_payload`) into a
**searchable RAG index**. For each not-yet-indexed document the system: picks **one representative
source payload** (highest reliability → richest → newest, never merging across a paper's sources —
FR-024), **parses** it by source type through a **parser router** into typed, section-aware
**chunks** (`text` / `table` / `figure_caption` / `structured_data`), **chunks** them to ~256 tokens
with ~15% overlap and a hard cap < 512 tokens — counted with the **embedder's own tokenizer** so no
medical text is ever silently truncated (FR-008/FR-025) — **embeds** every chunk via the Spec-5
medical ONNX embedder through the existing `ModelserverClient` (768-dim, L2-normalized), and
**persists** chunks to a new pgvector-backed `chunks` table, each carrying `client_id`, the document
link, `chunk_type`, section, `source_reliability`, a dense embedding, a lexical `tsvector`, the
embedder model version, and an ordinal. Per-document progress lives in a dedicated
`document_index_state` table; per-run counts in an `index_build_runs` table.

The build is **idempotent, incremental, resumable, and cause-aware**: an already-`indexed` document
is never re-processed; transient failures (`errored-transient`) are retried next run while
deterministic parse failures (`errored-permanent`) are not; each document's chunks + its
state-transition commit in **one transaction** (FR-028); and **only one build runs per client at a
time** (FR-026). The build is started by a **manual trigger endpoint** under
`/clients/{client_id}/...` requiring a staff **manager/admin** via `acting_client` (FR-017/FR-027),
executed via FastAPI `BackgroundTasks` — mirroring Spec 4's ingestion pattern exactly; cron/cycle
wiring stays Spec 11. Retrieval, reranking, corroboration, classification, drafting, Presidio
redaction, and cron are explicitly out of scope (Specs 7/8/9/11/12). This adds one Alembic migration
(`0006`) creating three tables + enabling the `vector` extension; **no Spec-4 table is altered**.

## Technical Context

**Language/Version**: Python 3.12+ (managed by `uv`).

**Primary Dependencies**:
- *Existing (reused)*: FastAPI, SQLAlchemy 2 (async) + asyncpg, Alembic, Pydantic v2,
  `app/infra/modelserver_client.py` (httpx + tenacity, with `embed_chunked`), structlog,
  `app/auth` guards (`require_admin`, `acting_client`), the domain-event dispatcher.
- *New runtime deps (added to `[project].dependencies`)*:
  - **`pgvector`** — SQLAlchemy `Vector(768)` column type + pgvector operators (the DB image is
    already `pgvector/pgvector:pg16`, so the extension is available; only `CREATE EXTENSION vector`
    in the migration is needed).
  - **`lxml`** — parse JATS XML (PubMed, Europe PMC) from the stored raw payloads.
  - **`tokenizers`** — load the embedder's `tokenizer.json` to count tokens **exactly** for chunk
    boundaries (FR-025). No torch; the Rust `tokenizers` wheel is lean and already proven in the
    `modelserver` group.
- *No new services.* This feature is **in-app** (an `app/embedding/` package + ARQ-callable runner),
  not a new container. It calls the existing modelserver over HTTP.

**Storage**: PostgreSQL (+ **pgvector**). One new migration `0006` enables the `vector` extension and
creates three tables — `chunks` (with a `Vector(768)` column, a `tsvector` lexical column, and
supporting indexes incl. an **HNSW** vector index), `document_index_state` (1:1 with `documents`),
and `index_build_runs`. **No Spec-4 table is altered.** Redis is not used here (query-embedding cache
is Spec 7).

**Testing**: `uv run pytest`. Unit tests: parser router dispatch; each parser on a committed fixture
payload (correct `chunk_type`, section tagging, table-row integrity, figure-caption isolation);
section-aware chunker (size/overlap/cap, exact token counting, oversized-section split); source
selection (FR-024); failure classification (transient vs permanent). Integration tests (live stack,
`PANTERA_INTEGRATION=1`): full build over seeded documents → chunks persisted with embeddings;
idempotent re-run (0 new chunks, 0 embed calls); client isolation; concurrent double-trigger → one
run, no duplicate chunks; PII-free logs (`capsys`/structlog); migration up **and** down on the live
DB. The embedder is consumed via the modelserver (live) or a stubbed `ModelserverClient` in unit
tests.

**Target Platform**: Linux container — the existing `api` service (and, in Spec 11, the `worker`)
in the docker-compose modular monolith. The runner is written framework-agnostically
(`session_factory` injected) so Spec 11's ARQ worker reuses it unchanged, exactly like
`run_ingestion`.

**Project Type**: Web service (modular monolith) — a new in-app domain module `app/embedding/`.

**Performance Goals**: A typical post-ingestion batch for a client is indexed within minutes
(SC-009, qualitative). Embedding is the bound; calls go through `embed_chunked` (≤128/request).
HNSW vector index gives sub-linear similarity search for Spec 7. No hard CI latency gate.

**Constraints**: Async throughout (`asyncio`, no `requests`/`time.sleep`); tenacity retries on the
embedder (no retry on 4xx); **no chunk reaches modelserver truncation** in normal operation
(boundaries computed with the embedder's tokenizer; truncation = logged error); **768-dim** fixed;
per-document **atomic** chunk+state commit; **one in-flight build per client**; multi-tenant scoping
on every query (every new row carries `client_id`); PII-free `structlog`; files ≤ ~300 lines with a
one-sentence docstring; ruff **and** black clean; coverage ≥ 80% overall (DB-write paths ≥ 95%).

**Scale/Scope**: Moderate per-client corpora (tens–thousands of documents per cycle). One new
in-app package, one migration (3 tables), one trigger endpoint + run-status reads, five source
parsers + router, a tokenizer-backed chunker, a runner, three new runtime deps. No CI eval-gate
addition (retrieval golden set is Spec 7).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Relevance | Status |
|-----------|-----------|--------|
| I. Human-in-the-Loop | No drafting/sending; pure index build. No autonomous determination. | ✅ N/A |
| II. Grounding (NON-NEGOTIABLE) | **Enabling + protective**: builds the citable chunk substrate retrieval grounds on; FR-025 exact-tokenizer chunking guarantees no medical text is silently truncated (a citation can never point at dropped text). | ✅ Enabling/Protective |
| III. Triage Fails Safe | Indexes **all** documents incl. eventual-irrelevant (cross-document context), so triage later has full evidence; transient failures retried (no silent document loss). | ✅ Enabling |
| IV. Backed by a Number | This spec adds **no** gated artifact (classifier/retrieval/agent/triage). Retrieval golden set + faithfulness gate are Spec 7; parsing/typing correctness is asserted by fixture tests (SC-005). No `eval_thresholds.yaml` change. | ✅ N/A (Spec 7 owns the RAG gate) |
| V. Multi-Tenant Isolation (NON-NEGOTIABLE) | Every new row (`chunks`, `document_index_state`, `index_build_runs`) carries `client_id`; all reads/writes client-scoped; trigger uses `acting_client` (server-validated target client, audit-attributed); a chunk for one client can never surface in another's index (SC-002). | ✅ Enforced |
| VI. Lean, Reproducible, Justified | **In-app, no new container** (complexity avoided). New deps are lean and no-torch (`pgvector`, `lxml`, `tokenizers`); embeddings served by the existing ONNX modelserver. `uv` lockfile; no MCP. | ✅ Aligned |
| VII. Own Every Line (Spec-Driven) | spec → clarify×2 → checklist → plan → tasks → implement; Conventional Commits; PRs < 400 lines (migration+models; parsers+router; chunker+tokenizer; runner+endpoint+tests as separable PRs); files ≤ 300 lines. | ✅ Aligned |

**Security & standards applied**: trigger endpoint requires staff `manager`/`admin` via
`require_admin` + `acting_client(client_id)` (FR-027, Constitution V compensating controls); chunk
text stored faithfully but **never logged** (PII-free `structlog`; FR-019), with active Presidio
redaction deferred to Spec 12; embedder calls wrapped in the existing tenacity policy (no retry on
4xx); the embedder **tokenizer/model version is verified at startup** (FR-025), extending the
project's model-artifact-validation discipline; chunks cascade-delete with their document (FR-020)
so Spec-12 erasure can purge them.

**Result**: PASS — no violations. Complexity Tracking intentionally empty (no new container, no new
external service, no torch; three lean deps justified by the parse/chunk/embed/store job).

## Project Structure

### Documentation (this feature)

```text
specs/006-parse-chunk-embed/
├── plan.md              # This file
├── research.md          # Phase 0 output (decisions D1–D12)
├── data-model.md        # Phase 1 output (3 tables: chunks, document_index_state, index_build_runs)
├── quickstart.md        # Phase 1 output (build/run/validate guide)
├── contracts/           # Phase 1 output
│   ├── index-trigger.md     # POST /clients/{id}/index (202 + run); auth; one-in-flight
│   ├── index-runs.md        # GET runs list + run detail + per-document index state
│   ├── parser-router.md     # source → parser dispatch + ParsedChunk shape contract
│   ├── chunk-record.md      # persisted chunk data contract (fields, types, invariants)
│   └── embedder-usage.md    # how the runner calls ModelserverClient + version verification
├── checklists/
│   ├── requirements.md          # spec-quality gate (from /speckit-specify)
│   └── implementation-readiness.md  # requirements QA (from /speckit-checklist)
└── tasks.md             # /speckit-tasks output (NOT created here)
```

### Source Code (repository root)

A new in-app **`app/embedding/`** domain package (mirroring `app/ingestion/`), one Alembic
migration, three new runtime deps, and the router registration in `app/main.py`. No existing module
changes beyond additive registration and `pyproject.toml`.

```text
app/embedding/                         # NEW in-app domain package (parse + chunk + embed)
├── __init__.py
├── enums.py                           # ChunkType, DocumentIndexStatus, IndexBuildRunStatus (StrEnum + CHECK mirror)
├── models.py                          # ORM: Chunk, DocumentIndexState, IndexBuildRun (+ Vector(768), tsvector)
├── schemas.py                         # Pydantic: IndexBuildRunOut, DocumentIndexStateOut (no ORM at API boundary)
├── selection.py                       # FR-024 representative-source picker (reliability→richness→recency)
├── router.py                          # parser router: source → parser; returns list[ParsedChunk]
├── parsers/
│   ├── __init__.py                    # PARSERS registry {source: parser}
│   ├── base.py                        # ParsedChunk dataclass + Parser protocol
│   ├── pubmed_jats.py                 # JATS XML → abstract/section text chunks + MeSH metadata
│   ├── europepmc_jats.py             # full JATS → text + table (header-per-row) + figure_caption
│   ├── openfda_faers.py               # structured JSON → natural-language structured_data chunk
│   ├── openfda_label.py               # label JSON → per-section chunks (section name retained)
│   └── regulatory_feed.py             # MedWatch/EMA/MHRA alert → summary chunk (regulatory_alert)
├── tokenizer.py                       # load embedder tokenizer.json; count_tokens(); startup version verify (FR-025)
├── chunking.py                        # section-aware splitter: ~256 target / ~15% overlap / <512 cap (FR-008)
├── service.py                         # DB ops: claim/finish run, upsert state, insert chunks, scoped reads
├── runner.py                          # orchestration: per-document parse→chunk→embed→persist (isolation, atomic, resumable)
└── routes.py                          # POST /clients/{id}/index ; GET runs/state (acting_client + require_admin)

app/db/migrations/versions/
└── 0006_chunks_index_state.py        # CREATE EXTENSION vector; chunks + document_index_state + index_build_runs; reversible

app/main.py                            # ADD: include_router(embedding_router)
pyproject.toml                         # ADD runtime deps: pgvector, lxml, tokenizers

tests/
├── unit/
│   ├── test_source_selection.py       # FR-024 reliability→richness→recency picker
│   ├── test_parser_router.py          # dispatch by source; unknown source handled
│   ├── test_parsers_pubmed.py         # JATS → text chunks + section labels + MeSH
│   ├── test_parsers_europepmc.py      # table header-per-row, no mid-row split; figure_caption isolated
│   ├── test_parsers_openfda.py        # FAERS structured_data serialization; label per-section
│   ├── test_parsers_regulatory.py     # alert summary chunk; regulatory_alert reliability inherited
│   ├── test_tokenizer_count.py        # exact token count vs embedder tokenizer; special-token reserve
│   ├── test_chunking.py               # target/overlap/cap; oversized section splits; structural no-overlap
│   └── test_index_failure_classify.py # transient→errored-transient (retry); parse→errored-permanent (skip)
└── integration/
    ├── test_index_build.py            # full build: chunks + 768 embedding + version + ordinal; indexed-empty
    ├── test_index_idempotency.py      # re-run: 0 new chunks, 0 embed calls; +1 doc → only that doc
    ├── test_index_isolation.py        # cross-client read returns 0 foreign chunks (SC-002)
    ├── test_index_concurrency.py      # double-trigger → one run, 0 duplicate chunks (FR-026)
    ├── test_index_auth.py             # reviewer/client-user → 403; manager/admin → 202 (FR-027)
    ├── test_index_no_pii_logs.py      # FAERS de-identified attrs never in logs (FR-019, SC-007)
    └── test_migration_0006.py         # upgrade + downgrade on the live DB; extension + tables + indexes
```

**Structure Decision**: Build Spec 6 as an **in-app domain package** `app/embedding/` that mirrors
the proven `app/ingestion/` shape (enums, models, schemas, service, runner, routes + a parsers
subpackage), because parse/chunk/embed is core business logic operating on the platform's own data
and the modelserver already isolates the only no-torch concern. The runner takes an injected
`session_factory` (like `run_ingestion`) so Spec 11's ARQ worker reuses it without change. Embedding
is delegated to the existing `app/infra/modelserver_client.py` (`embed_chunked`), keeping the lean
container boundary intact. ORM models live in `app/embedding/models.py` (matching
`app/ingestion/models.py`), with the schema realized in Alembic migration `0006`.

## Complexity Tracking

> No constitution violations — table intentionally empty. The feature adds **no** new container and
> **no** new external service (embedding reuses the existing modelserver). The three new runtime
> deps (`pgvector`, `lxml`, `tokenizers`) are lean, no-torch, and each maps directly to a required
> capability (vector storage, JATS parsing, exact token counting for grounding-safe chunking).
