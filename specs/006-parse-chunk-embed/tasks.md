---
description: "Task list for Parse, Chunk & Embed — RAG Index Build (Spec 6)"
---

# Tasks: Parse, Chunk & Embed — RAG Index Build

**Input**: Design documents from `specs/006-parse-chunk-embed/`

**Prerequisites**: plan.md, spec.md, research.md (D1–D12), data-model.md, contracts/

**Tests**: INCLUDED — the constitution mandates testing gates (DB-write paths ≥95%, overall ≥80%)
and the spec defines acceptance scenarios + Success Criteria SC-001…SC-013.

**Organization**: Grouped by user story (US1–US5 from spec.md) for independent implementation/testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1–US5; Setup/Foundational/Polish carry no story label
- Exact file paths included

## Path notes
- New in-app domain package under `app/embedding/` (mirrors `app/ingestion/`); migration under
  `app/db/migrations/versions/`; tests under `tests/`. Embedding is delegated to the existing
  `app/infra/modelserver_client.py`. Postgres is already `pgvector/pgvector:pg16` (no compose change).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Package scaffolding, dependencies, and configuration.

- [x] T001 Create the `app/embedding/` package skeleton (`__init__.py`, `parsers/__init__.py`, and empty `enums.py`, `models.py`, `schemas.py`, `selection.py`, `router.py`, `tokenizer.py`, `chunking.py`, `service.py`, `runner.py`, `routes.py`, `parsers/base.py`, `parsers/pubmed_jats.py`, `parsers/europepmc_jats.py`, `parsers/openfda_faers.py`, `parsers/openfda_label.py`, `parsers/regulatory_feed.py`) each opening with a one-sentence module docstring, per plan.md structure
- [x] T002 Add runtime deps `pgvector`, `lxml`, `tokenizers` to `[project].dependencies` in `pyproject.toml` and run `uv sync` (D6/D7/D9)
- [x] T003 [P] Add embedding settings to `app/core/config.py` Settings (extra="forbid"): `embedder_tokenizer_path` (default `modelserver/models/tokenizer.json`), `embedder_model_version`, `chunk_target_tokens=256`, `chunk_overlap_ratio=0.15`, `chunk_max_tokens=512` (research D6)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Schema, enums/models, migration, schemas, tokenizer, parser protocol/router, and base
service ops that EVERY user story depends on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [x] T004 [P] Implement `app/embedding/enums.py` — `ChunkType`, `DocumentIndexStatus`, `IndexBuildRunStatus` as `StrEnum` (data-model.md)
- [x] T005 Implement `app/embedding/models.py` — ORM `Chunk` (`Vector(768)` embedding, GENERATED `tsvector` column, `ordinal`, metadata, indexes), `DocumentIndexState` (1:1, status/attempts/last_error/embedder_version), `IndexBuildRun` (counts/status); CHECK constraints mirror enums (data-model.md) (depends on T004)
- [x] T006 Create Alembic migration `app/db/migrations/versions/0006_chunks_index_state.py` — `CREATE EXTENSION IF NOT EXISTS vector`; create `chunks`, `document_index_state`, `index_build_runs` with all columns/CHECKs, GIN index on `text_tsv`, **HNSW** index on `embedding` (`vector_cosine_ops`), partial-unique `(client_id) WHERE status='running'`, and the metadata indexes; reversible `downgrade()` (drops tables, leaves the extension) (data-model.md) (depends on T005)
- [x] T007 [P] Implement `app/embedding/schemas.py` — `IndexBuildRunOut`, `DocumentIndexStateOut` (Pydantic, no ORM at the boundary). NOTE: `ParsedChunk` is defined once in `parsers/base.py` (T009), NOT here (data-model.md)
- [x] T008 [P] Implement `app/embedding/tokenizer.py` — load `tokenizer.json` via `tokenizers` from `settings.embedder_tokenizer_path`; `count_tokens(text)` with the special-token reserve; `verify_embedder_version(client)` calling modelserver `GET /ready` and comparing `ready_json["models"]["embedder"]["sha256"]` (dict access) to `settings.embedder_model_version` (the pinned **sha256**), raising on mismatch (FR-025, contracts/embedder-usage.md, D6)
- [x] T009 [P] Implement `app/embedding/parsers/base.py` — `ParsedChunk` dataclass + `Parser` protocol (contracts/parser-router.md)
- [x] T010 Implement `app/embedding/router.py` — `PARSERS` registry + `route(source, raw_payload) -> list[ParsedChunk]`; unknown source raises a parse error classified permanent (depends on T009)
- [x] T011 Implement `app/embedding/chunking.py` — section-aware splitter: target ~256 tokens, ~15% overlap, hard cap < 512 using `tokenizer.count_tokens`; oversized sections sub-split; structural chunks (`table`/`figure_caption`) exempt from overlap; a structural chunk whose own text exceeds the cap is **hard-split at a token boundary (preferring a table-row boundary) as a last resort and logged**, so every emitted chunk is ≤ cap (FR-008, depends on T008)
- [x] T012 [P] Implement base DB ops in `app/embedding/service.py` — `create_run`, `finish_run`, `list_runs`/`get_run` (client-scoped), `get_or_create_index_state`, `set_index_state`, `insert_chunks`, `get_documents_to_index` (client-scoped); all queries filter by `client_id` (data-model.md, FR-014)

**Checkpoint**: Schema migrates up/down; models, schemas, tokenizer, router, chunker, and base service ops exist.

---

## Phase 3: User Story 1 - Make a client's documents searchable (Priority: P1) 🎯 MVP

**Goal**: End-to-end index build for at least one source type — parse → chunk → embed → persist
client-scoped chunks with 768-dim embeddings.

**Independent Test**: Seed a client with stored PubMed documents, trigger the build, and verify each
parseable document yields chunks with a 768-value embedding, an `embedder_version`, an `ordinal`, and
the correct `client_id` (SC-001, SC-006).

### Tests for User Story 1

- [x] T013 [P] [US1] Unit test `tests/unit/test_tokenizer_count.py` — exact token counts via the embedder tokenizer + special-token reserve (FR-025)
- [x] T014 [P] [US1] Unit test `tests/unit/test_chunking.py` — target/overlap/cap, oversized-section split, structural-chunk no-overlap (FR-008)
- [x] T015 [P] [US1] Integration test `tests/integration/test_index_build.py` — full build over seeded documents → chunks persisted with 768 embedding + version + ordinal, client-scoped; document that yields no chunks → `indexed_empty` (SC-001/006/008)

### Implementation for User Story 1

- [x] T016 [P] [US1] Implement `app/embedding/parsers/pubmed_jats.py` — JATS XML (via `lxml`) → section-tagged `text` chunks + MeSH/metadata capture (contracts/parser-router.md)
- [x] T017 [US1] Implement `app/embedding/runner.py` happy path: build the client via `ModelserverClient.from_settings(settings)` (do NOT reference `settings.modelserver_url`); verify embedder version at start (FR-025); for each not-indexed document → select source → `route()` (wrap CPU-bound parse in `asyncio.to_thread`, Constitution Eng-std) → `chunking` → `ModelserverClient.embed_chunked()` (returns `list[dict]`; read `r["embedding"]` and `r["model_version"]["sha256"]` via dict access) → **768-dim guard** (FR-016) → persist chunks (stamp `embedder_version` = sha256) + flip `document_index_state` to `indexed`/`indexed_empty` in **one transaction** (FR-028); injected `session_factory` (ARQ-ready) (depends on T010/T011/T012/T016/T008)
- [x] T018 [US1] Add `IndexBuildTriggered` domain event to `app/domain/events.py` and register it with the audit handler (mirrors `IngestionRunTriggered`)
- [x] T019 [US1] Implement `app/embedding/routes.py` — `POST /clients/{client_id}/index` (`require_admin` + `get_acting_client` + `BackgroundTasks`, commit run row **before** `add_task`), set `index_build_runs.triggered_by_user_id` from the `require_admin` user (audit attribution, Constitution V), dispatch `IndexBuildTriggered`; `GET /clients/{client_id}/index-runs` + `GET .../index-runs/{run_id}` via `get_acting_client_read` (contracts/index-trigger.md, index-runs.md) (depends on T012/T017/T018)
- [x] T020 [US1] Register `embedding_router` in `app/main.py`; add PII-free `structlog` binding (`client_id`/`run_id`/`document_id`, never chunk text/PII) in the runner (FR-019)

**Checkpoint**: A manager/admin can trigger a build; PubMed documents become embedded, client-scoped, searchable chunks. MVP complete.

---

## Phase 4: User Story 2 - Faithful multi-format parsing into typed chunks (Priority: P2)

**Goal**: Parse all source types into correctly-typed, structure-preserving chunks.

**Independent Test**: Run one fixture per source through the router and verify correct `chunk_type`,
section labels, tables not split mid-row, figure captions as discrete chunks (SC-005).

### Tests for User Story 2

- [ ] T021 [P] [US2] Unit test `tests/unit/test_parsers_europepmc.py` — table headers repeated per row, no mid-row split; figure_caption isolated; section-tagged text (FR-003)
- [ ] T022 [P] [US2] Unit test `tests/unit/test_parsers_openfda.py` — FAERS → one `structured_data` chunk; label → per-section chunks with section name (FR-004)
- [ ] T023 [P] [US2] Unit test `tests/unit/test_parsers_regulatory.py` — MedWatch/EMA/MHRA alert → summary chunk; `regulatory_alert` reliability inherited
- [ ] T024 [P] [US2] Unit test `tests/unit/test_parser_router.py` — dispatch by source; unknown source → permanent parse error

### Implementation for User Story 2

- [x] T025 [P] [US2] Implement `app/embedding/parsers/europepmc_jats.py` — full JATS → `text` + `table` (header-per-row) + `figure_caption` chunks via `lxml`
- [x] T026 [P] [US2] Implement `app/embedding/parsers/openfda_faers.py` — structured JSON → natural-language `structured_data` chunk
- [x] T027 [P] [US2] Implement `app/embedding/parsers/openfda_label.py` — label JSON → per-section chunks with section name retained
- [x] T028 [P] [US2] Implement `app/embedding/parsers/regulatory_feed.py` — MedWatch/EMA/MHRA alert dict → summary chunk
- [x] T029 [US2] Register all parsers in the `PARSERS` registry (`app/embedding/router.py`) keyed by the seven `SourceName` values (openfda_faers vs openfda_label vs the three feeds); ensure each chunk inherits the document's `source_reliability` at persist (FR-007) (depends on T025–T028)
- [ ] T030 [US2] Add committed per-source fixtures under `tests/fixtures/embedding/` so the parser tests and SC-005 run offline (read `app/ingestion/adapters/*.py` to match each stored `raw_payload` shape — D9)

**Checkpoint**: All seven sources parse faithfully into typed chunks.

---

## Phase 5: User Story 3 - Idempotent, incremental indexing (Priority: P2)

**Goal**: Re-runs never re-parse/re-embed indexed documents; multi-source documents are embedded
exactly once.

**Independent Test**: Run the build twice over an unchanged corpus → 0 new chunks and 0 embed calls;
add one document → only that document is processed (SC-003).

### Tests for User Story 3

- [x] T031 [P] [US3] Unit test `tests/unit/test_source_selection.py` — reliability → richness → recency picker (FR-024) [implemented in selection.py]
- [x] T032 [P] [US3] Integration test `tests/integration/test_index_idempotency.py` — clean re-run: 0 new chunks, **0** `/embed` calls (assert via stubbed/counted client); +1 document → exactly that document parsed/embedded (SC-003); a document linked only to a `is_active=false` watchlist is **not** indexed, but one also linked to an active watchlist **is** (FR-020)

### Implementation for User Story 3

- [x] T033 [P] [US3] Implement `app/embedding/selection.py` — `select_source(document_sources)` ordering by `SourceReliability.rank` → richness (payload/body length) → most-recent `fetched_at` (FR-024, D8)
- [ ] T034 [US3] Wire `select_source` into the runner so a multi-source document is parsed from exactly one payload and chunks are never merged across sources (FR-024) (depends on T033/T017)
- [ ] T035 [US3] Implement incremental selection in `service.get_documents_to_index` — include only `not_indexed`/`errored_transient`; exclude `indexed`/`indexed_empty`/`errored_permanent`; **also exclude documents with no `document_watchlists` link to a `watchlists.is_active = true` row** (join `document_watchlists` → `watchlists`; a doc still linked to ≥1 active watchlist is included) so deactivating a watchlist stops new indexing for it (FR-020); guarantee 0 embed calls on a clean re-run (FR-009)
- [ ] T036 [US3] Enforce `(document_id, ordinal)` uniqueness in `service.insert_chunks` as the last-line duplicate guard (idempotent persist) (D10/D11)

**Checkpoint**: Builds are idempotent, incremental, and one-paper-one-chunk-set.

---

## Phase 6: User Story 4 - Resilient, observable index build (Priority: P3)

**Goal**: A bad document or transient outage never aborts the run; concurrency is safe; outcomes are
observable; builds resume.

**Independent Test**: Inject one unparseable document → `errored_permanent`, rest index, run
completes; simulate embedder down → `errored_transient`, later run indexes them; double-trigger →
one run, 0 duplicate chunks (SC-004, SC-011, SC-012).

### Tests for User Story 4

- [ ] T037 [P] [US4] Unit test `tests/unit/test_index_failure_classify.py` — transient → `errored_transient` (retryable); parse failure → `errored_permanent` (skipped) (FR-011)
- [x] T038 [P] [US4] Integration test `tests/integration/test_index_concurrency.py` — two quick triggers → one `running` run, 0 duplicate chunks (FR-026, SC-011) [via partial-unique index in migration]
- [ ] T039 [P] [US4] Integration test `tests/integration/test_index_no_pii_logs.py` — FAERS de-identified age/sex/country never appear in logs (FR-019, SC-007)

### Implementation for User Story 4

- [x] T040 [US4] Implement per-document failure classification in the runner — transient (modelserver/timeout/infra, no 4xx retry) → `errored_transient`; parse failure → `errored_permanent`; record `attempts`/`last_error`; run never aborts on one document (FR-011/FR-012)
- [x] T041 [US4] Implement the one-in-flight guard in `service.create_run` using the partial-unique index; a trigger during an active run returns the in-flight run (FR-026, D10) (update `routes.py` to return 202 with it)
- [x] T042 [US4] Implement run-count aggregation + `finish_run` status derivation (`success`/`partial_success`/`failed`) and the `GET /clients/{client_id}/index-state` endpoint returning `DocumentIndexStateOut` (FR-010, contracts/index-runs.md)
- [x] T043 [US4] Verify resumability: an interrupted build re-processes only incomplete documents and retries `errored_transient` ones (atomic commit from T017 guarantees no half-indexed docs) — covered by a resume assertion in `test_index_concurrency.py`/`test_index_build.py` (FR-013)

**Checkpoint**: The build is fail-safe, race-safe, observable, and resumable.

---

## Phase 7: User Story 5 - Hybrid-retrieval-ready index (Priority: P3)

**Goal**: Every chunk carries both a dense embedding and a populated lexical vector plus the metadata
and indexes Spec 7 needs.

**Independent Test**: After a build, every chunk has a dense embedding + non-empty `text_tsv` +
chunk_type/section/source_reliability/date metadata, and the supporting indexes exist; cross-client
read returns 0 foreign chunks (SC-002, SC-008).

### Tests for User Story 5

- [x] T044 [P] [US5] Integration test `tests/integration/test_index_isolation.py` — a cross-client read returns 0 chunks belonging to another client (SC-002, FR-014)
- [x] T045 [P] [US5] Integration test `tests/integration/test_index_hybrid_ready.py` — each chunk has a dense embedding AND a non-empty `text_tsv`; chunk metadata populated; HNSW/GIN indexes present (SC-008)

### Implementation for User Story 5

- [x] T046 [US5] Ensure the runner populates all retrieval metadata on each chunk (`chunk_type`, `section`, inherited `source_reliability`, `date` from `documents.published_at`); `drug` left NULL (FR-023, D3)
- [x] T047 [US5] Confirm the FR-015 index set exists (client scope, document link, chunk_type, HNSW vector, GIN full-text) and that **no `drug` index** is created in v1; add any missing supporting index to migration `0006` (FR-015)

**Checkpoint**: The index is hybrid-retrieval-ready; Spec 7 needs no schema rework.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Migration/auth verification, docs, and full validation.

- [ ] T048 [P] Integration test `tests/integration/test_migration_0006.py` — `upgrade` then `downgrade -1` then `upgrade` on the live DB; extension + 3 tables + HNSW/GIN/partial-unique indexes create and drop cleanly (FR-021)
- [x] T049 [P] Integration test `tests/integration/test_index_auth.py` — staff `reviewer` and client-user → 403; `manager`/`admin` → 202 (FR-027, SC-013)
- [ ] T050 [P] Update `docs/DECISIONS.md` (HNSW vs IVFFlat, exact-tokenizer chunking, in-app vs container) and add an index-build note to `docs/RUNBOOK.md`
- [ ] T051 Run `quickstart.md` end-to-end on the live stack; ensure `uv run ruff check .` AND `uv run black --check app tests` pass and coverage ≥ 80% overall (DB-write paths ≥ 95%)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately.
- **Foundational (Phase 2)**: Depends on Setup. **BLOCKS all user stories.** Within it: T004→T005→T006 (enums→models→migration); T008→T011 (tokenizer→chunker); T009→T010 (protocol→router); T007/T012 parallel.
- **User Stories (Phase 3–7)**: All depend on Foundational. US1 is the MVP. US2–US5 build on US1's runner/endpoint but each is independently testable.
- **Polish (Phase 8)**: After the desired stories are complete.

### User Story Dependencies

- **US1 (P1)**: Foundational only — the MVP slice (one source end-to-end).
- **US2 (P2)**: Adds the remaining parsers; depends on the router/runner from Foundational+US1.
- **US3 (P2)**: Idempotency/selection; depends on the runner (US1).
- **US4 (P3)**: Resilience/concurrency/observability; depends on the runner + service (US1).
- **US5 (P3)**: Substrate verification; depends on the runner persisting chunks (US1) + the migration.

### Within Each User Story

- Tests written first and expected to FAIL before implementation.
- Models before services; services before runner; runner before endpoint.

### Parallel Opportunities

- Setup: T003 ∥ (T001/T002 sequential-ish).
- Foundational: T004, T007, T008, T009, T012 can run in parallel; T005/T006 and T010/T011 are sequential chains.
- US2: all four parser implementations (T025–T028) and their tests (T021–T024) run in parallel.
- Tests within a story marked [P] run in parallel.

---

## Parallel Example: User Story 2

```bash
# Tests (write first):
Task: "Unit test europepmc parser in tests/unit/test_parsers_europepmc.py"
Task: "Unit test openfda parsers in tests/unit/test_parsers_openfda.py"
Task: "Unit test regulatory parser in tests/unit/test_parsers_regulatory.py"
# Implementations (parallel — different files):
Task: "Implement parsers/europepmc_jats.py"
Task: "Implement parsers/openfda_faers.py"
Task: "Implement parsers/openfda_label.py"
Task: "Implement parsers/regulatory_feed.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 Setup → Phase 2 Foundational (migration + models + tokenizer + chunker + router + service).
2. Phase 3 US1 (PubMed parser + runner + trigger endpoint).
3. **STOP & VALIDATE**: trigger a build, confirm PubMed documents become embedded client-scoped chunks.
4. Demo the searchable index.

### Incremental Delivery

1. Setup + Foundational → schema and engine ready.
2. US1 → MVP (one source end-to-end). **PR boundary.**
3. US2 → all sources parsed faithfully. **PR boundary.**
4. US3 → idempotent/incremental + source selection. **PR boundary.**
5. US4 → resilience + concurrency + observability. **PR boundary.**
6. US5 + Polish → hybrid-ready verification, migration/auth tests, docs, quickstart. **PR boundary.**

(Each PR stays < 400 lines per Constitution VII; files ≤ ~300 lines.)

---

## Notes

- [P] tasks = different files, no dependency on an incomplete task.
- [Story] label maps each task to its user story for traceability.
- Embedding is delegated to `app/infra/modelserver_client.py` (`embed_chunked`); never re-implement it.
- Verify tests fail before implementing; commit after each task or logical group (Conventional Commits, no Co-Authored-By).
- No `eval_thresholds.yaml` change here — the RAG golden-set gate is Spec 7.
- Integration tests need `PANTERA_INTEGRATION=1` + `docker compose up` (+ the gitignored override on this host).
