---
description: "Task list for literature-ingestion (spec 4)"
---

# Tasks: Literature Ingestion

**Input**: Design documents from `specs/004-literature-ingestion/`
**Prerequisites**: plan.md, spec.md, research.md (D1–D16), data-model.md, contracts/

**Tests**: INCLUDED — the constitution mandates ≥95% coverage on DB-write paths and the spec's
success criteria (SC-003/007/010/011) are behavioral; tasks are test-driven per story.

**Organization**: By user story (US1–US5) for independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: parallelizable (different files, no incomplete-task dependency)
- **[Story]**: US1–US5; Setup/Foundational/Polish carry no story label
- All paths are repo-relative.

---

## Phase 1: Setup (Shared Infrastructure)

- [X] T001 Promote `httpx` from `[dependency-groups].dev` to runtime `[project].dependencies` in `pyproject.toml`, then `uv lock` + `uv sync` (D6).
- [X] T002 [P] Create the `app/ingestion/` package skeleton (`__init__.py`, `adapters/__init__.py`, empty `data/` dir) per plan structure.
- [X] T003 [P] Create fixture directories `tests/fixtures/{pubmed,europepmc,openfda,fda_medwatch,ema,mhra}/` for recorded adapter payloads (D16).

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ CRITICAL**: The shared ingestion engine — no user story can be implemented until this completes.

- [X] T004 [P] Define enums in `app/ingestion/enums.py`: `SourceName`, `SourceReliability` (+`.rank`), `IngestionRunStatus`, `SourceRunStatus`, `MeshValidity` (D3, data-model).
- [X] T005 [P] Implement normalized-identifier precedence (DOI→PMID→`<source>:<id>`, namespaced/lowercased) in `app/ingestion/identifiers.py` (pure, D4).
- [X] T006 [P] Implement shared async HTTP in `app/infra/http.py`: `httpx.AsyncClient` factory (timeouts, UA + `ncbi_tool_email`) + `tenacity` retry helper (3 attempts, expo backoff, retry timeouts/5xx, never 4xx) + per-source `asyncio.Semaphore` (D6, Constitution).
- [X] T007 Define the six ORM models in `app/ingestion/models.py` (`documents`, `document_sources`, `document_watchlists`, `ingestion_runs`, `ingestion_run_sources`, `source_watermarks`) with CHECKs + indexes per data-model.md.
- [X] T008 Create Alembic migration `app/db/migrations/versions/0004_ingestion.py`: the six tables + indexes + additive `watchlist_items.mesh_validity`/`mesh_canonical` columns; reversible downgrade (D15) (depends T007).
- [X] T009 [P] Define Pydantic boundary schemas in `app/ingestion/schemas.py`: `IngestionRunOut` (+nested source/counts), `DocumentOut`, `DocumentDetailOut`, document filter params (no ORM leakage) per contracts/.
- [X] T010 Define the adapter contract in `app/ingestion/adapters/__init__.py`: `RawRecord` dataclass, `WatchlistQuery`, `SourceAdapter` Protocol, and an `ENABLED_ADAPTERS` registry (initially empty) (D5, contracts/source-adapter.md).
- [X] T011 Implement persistence core in `app/ingestion/service.py`: race-safe dedup upsert (`INSERT … ON CONFLICT (client_id, normalized_external_id) DO NOTHING` + savepoint flush, spec-3 pattern), `document_sources`/`document_watchlists` upserts, reliability recompute (max rank), watermark read/advance, run + per-source record create/update with counts (D10).
- [X] T012 Implement the runner skeleton in `app/ingestion/runner.py`: build `WatchlistQuery` (valid/unvalidated MeSH only), fan-out over `ENABLED_ADAPTERS` via `asyncio.gather`, aggregate counts, call `service` to persist; takes a session-factory so it is reusable by spec-11 ARQ (D8) (depends T010, T011).
- [X] T013 [P] Add `IngestionRunTriggered(DomainEvent)` to `app/domain/events.py` and a `run_id`→`ingestion_run` (and `watchlist_id`) target mapping in `app/audit/handler.py` `_target_for` (D14).
- [X] T014 [P] Extend `app/core/config.py`: optional secret `pubmed_api_key`/`openfda_api_key` (empty default, NOT in `_REQUIRED_SECRETS`), non-secret `ncbi_tool_email`, `ingestion_initial_lookback_days=365`, `ingestion_per_source_cap=200` (D7, D9).
- [X] T015 Extend `app/core/lifespan.py`: verify the bundled MeSH artifact exists (non-fatal warn if missing) and run the startup sweep flipping any `running` ingestion run → `failed` with `finished_at` (D8, D11, FR-024).

**Checkpoint**: Engine ready — user stories can begin.

---

## Phase 3: User Story 1 - Trigger a run and persist documents (Priority: P1) 🎯 MVP

**Goal**: An admin triggers ingestion for an active watchlist; PubMed records are fetched, normalized, persisted client-scoped, and visible; the run is audited and observable.

**Independent Test**: `POST /watchlists/{id}/ingest` as admin → 202; run completes; `GET /documents` shows the persisted PubMed documents scoped to the client; reviewer 403, cross-tenant 404, empty/inactive 400; one audit row.

### Tests (write first)

- [X] T016 [P] [US1] Trigger authz/eligibility integration test (admin 202, reviewer 403, cross-tenant 404, empty/inactive 400, one audit row) in `tests/integration/test_ingest_trigger.py`.
- [X] T017 [P] [US1] PubMed adapter parsing unit test (fixture → `RawRecord`) in `tests/unit/test_adapters_parsing.py`.

### Implementation

- [X] T018 [US1] Implement `app/ingestion/adapters/pubmed.py` (E-utilities esearch/efetch, MeSH targeting, stdlib `xml.etree` → `RawRecord`); register it in `ENABLED_ADAPTERS`.
- [X] T019 [US1] Implement `app/ingestion/routes_ingestion.py`: `POST /watchlists/{watchlist_id}/ingest` (`require_admin`, eligibility/scoping checks, create run, raise `IngestionRunTriggered`, schedule runner via `BackgroundTasks`, return 202) + `GET /watchlists/{id}/ingestion-runs` + `GET /ingestion-runs/{run_id}` (admin+reviewer) per contracts/ingestion-runs.md.
- [X] T020 [US1] Implement `app/ingestion/routes_documents.py`: `GET /documents` + `GET /documents/{document_id}` (client-scoped, admin+reviewer) per contracts/documents.md.
- [X] T021 [US1] Register `ingestion_router` + `documents_router` in `app/main.py`.
- [X] T022 [US1] Bind `client_id`/`run_id` with `structlog` in runner + routes; ensure no payload/PII in logs.

**Checkpoint**: MVP — single-source ingestion works end-to-end and is independently demoable.

---

## Phase 4: User Story 2 - All six sources + reliability tagging (Priority: P1)

**Goal**: A run fans out across all six sources behind the uniform contract, each normalized and tagged with the correct reliability tier; the corpus is browsable per source/tier.

**Independent Test**: Trigger a run; confirm every source is queried and normalized; each document carries the correct tier (MedWatch→`regulatory_alert`, PubMed→`peer_reviewed`, preprint→`preprint`, FAERS→`case_report`); `GET /documents?source=&reliability=` filters work.

### Tests (write first)

- [X] T023 [P] [US2] Adapter parsing unit tests for europepmc/openfda(FAERS+label)/medwatch/ema/mhra fixtures in `tests/unit/test_adapters_parsing.py`.
- [X] T024 [P] [US2] Reliability ordering + highest-contributing resolution unit test in `tests/unit/test_reliability.py`.
- [X] T025 [P] [US2] Multi-source run + per-tier tagging integration test in `tests/integration/test_documents_api.py`.

### Implementation

- [X] T026 [P] [US2] Implement `app/ingestion/adapters/europepmc.py` (REST JSON → `RawRecord`, DOI/PMID capture).
- [X] T027 [P] [US2] Implement `app/ingestion/adapters/openfda.py` (FAERS + drug-label endpoints → `openfda_faers`/`openfda_label` `RawRecord`s, JSON).
- [X] T028 [P] [US2] Implement `app/ingestion/adapters/fda_medwatch.py` (RSS/XML alert feed, stdlib parsing → `RawRecord`, tier `regulatory_alert`).
- [X] T029 [P] [US2] Implement `app/ingestion/adapters/ema.py` (safety feed; sequenced last per schedule-risk plan).
- [X] T030 [P] [US2] Implement `app/ingestion/adapters/mhra.py` (drug-safety feed; sequenced last).
- [X] T031 [US2] Register all adapters in `ENABLED_ADAPTERS` with correct `reliability`; confirm each consumes only its understood watchlist fields (FR-002) (depends T026–T030).
- [X] T032 [US2] Add `source`/`reliability`/`watchlist_id` filters to `GET /documents` in `routes_documents.py` + `service.py`.

**Checkpoint**: Full multi-source corpus with correct reliability tiers.

---

## Phase 5: User Story 3 - Deduplicate by normalized identifier (Priority: P2)

**Goal**: One real paper is stored once per client across re-runs and overlapping sources; corroboration is never inflated; per-client isolation holds.

**Independent Test**: Re-run with no new records → 0 created, all skipped; same paper from PubMed+Europe PMC → one document with both contributing sources and the highest tier; same record for two clients → two separate documents.

### Tests (write first)

- [X] T033 [P] [US3] Re-run zero-duplicate + created/skipped counts integration test in `tests/integration/test_ingest_dedup.py`.
- [X] T034 [P] [US3] Cross-source collapse (one doc, both sources, highest tier) + within-run dedup test in `tests/integration/test_ingest_dedup.py`.
- [X] T035 [P] [US3] Per-client isolation (same record, two clients → two docs, no cross-read) test in `tests/integration/test_ingest_dedup.py`.
- [X] T036 [P] [US3] Identifier normalization precedence + unidentifiable→errored unit test in `tests/unit/test_identifiers.py`.

### Implementation

- [X] T037 [US3] Finalize cross-source merge in `app/ingestion/service.py`: on dedup hit add `document_sources`, recompute `documents.source_reliability = max(rank)`, upsert `document_watchlists`, bump `last_fetched_at` (refines T011).
- [X] T038 [US3] Enforce within-run dedup in `app/ingestion/runner.py` (same normalized id surfaced twice in one run stored once) and count it as skipped; unidentifiable records → `errored_count` (FR-006/FR-014).

**Checkpoint**: Dedup correct across runs, sources, and tenants.

---

## Phase 6: User Story 4 - Validate watchlist MeSH terms (Priority: P2)

**Goal**: MeSH terms are validated at save time against the bundled slim list, validity persisted and visible on watchlist reads, re-checked at run time; flags never block; missing artifact degrades to `unvalidated`.

**Independent Test**: Add a valid + a bogus MeSH term to a watchlist → valid resolved, bogus flagged `invalid`, nothing rejected; PubMed run uses valid terms; remove the artifact → terms read `unvalidated`, ingestion still runs.

### Tests (write first)

- [X] T039 [P] [US4] MeSH `validate()` unit test (valid/invalid/unvalidated + missing-artifact degradation) in `tests/unit/test_mesh_validation.py`.
- [X] T040 [P] [US4] Save-time validation integration test on the spec-3 watchlist write path in `tests/integration/test_mesh_savetime.py`.

### Implementation

- [X] T041 [P] [US4] Add bundled `app/ingestion/data/mesh_terms.txt` (slim canonical list) + a generation note/operator script reference (D11).
- [X] T042 [US4] Implement `app/ingestion/mesh.py`: load list into a frozenset cached on `app.state`, `validate(term)->(MeshValidity, canonical|None)`; wire the startup presence check (with T015).
- [X] T043 [US4] Enhance `app/clients/service.py` + `app/clients/routes_watchlists.py`: on add/edit of a `mesh` item, call the validator and persist `mesh_validity`/`mesh_canonical` (flag never block).
- [X] T044 [US4] Surface `mesh_validity`/`mesh_canonical` in the spec-3 watchlist item read schema (`app/clients/schemas.py`).
- [X] T045 [US4] In `app/ingestion/runner.py`, build `WatchlistQuery` excluding `invalid` MeSH and defensively re-check before PubMed targeting (FR-010).

**Checkpoint**: Spec-3 MeSH carryover closed; validation visible and non-blocking.

---

## Phase 7: User Story 5 - Resilient, observable runs (Priority: P3)

**Goal**: Per-source failures are isolated (partial success), runs are incremental via watermarks, interrupted runs are reconciled, and every trigger is audited.

**Independent Test**: Make one source fail → run `partial_success`, others persist, failed source's watermark not advanced; leave a run `running` and restart → reconciled to `failed`, re-run creates no duplicates; second run fetches only newer records.

### Tests (write first)

- [X] T046 [P] [US5] Per-source failure isolation + `partial_success` + error captured integration test in `tests/integration/test_ingest_resilience.py`.
- [X] T047 [P] [US5] Interrupted-run startup sweep (`running`→`failed`) + safe re-run integration test in `tests/integration/test_ingest_resilience.py`.
- [X] T048 [P] [US5] Incremental watermark advance + first-run lookback (SC-010) integration test in `tests/integration/test_ingest_incremental.py`.
- [X] T049 [P] [US5] One-audit-row-per-trigger (SC-008) integration test in `tests/integration/test_ingest_trigger.py`.
- [X] T059 [P] [US5] Lifecycle/preservation integration test (FR-022): deactivating a watchlist / suspending its client refuses a **new** trigger (400) while an in-flight run still records its result and already-ingested documents, provenance, runs, and watermarks are **preserved** (no destructive delete) — in `tests/integration/test_ingest_resilience.py`.
- [X] T060 [P] [US5] Zero-result success assertion (FR-015): a source returning `[]` yields run `success` with `created=0` and `errored=0` (not a failure) — extend `tests/integration/test_ingest_resilience.py`.
- [X] T061 [P] [US5] PII-free logging assertion (FR-023): with a fake FAERS payload carrying a patient attribute, capture emitted `structlog` output and assert the attribute/raw payload never appears — in `tests/integration/test_ingest_resilience.py`.

### Implementation

- [X] T050 [US5] In `app/ingestion/runner.py`, wrap each source in try/except → write `ingestion_run_sources` rows (status + captured error) without aborting others; derive overall `IngestionRunStatus` (success/partial_success/failed) (FR-011/FR-012).
- [X] T051 [US5] Implement incremental windowing in runner/`service.py`: compute `since` from the per-`(watchlist,source)` watermark or `now − initial_lookback`; apply `per_source_cap`; advance watermark only on source success; dateless-source cursor fallback (D9, FR-021).
- [X] T052 [US5] Finalize the startup reconciliation sweep + `finished_at` in `app/core/lifespan.py` (with T015) and confirm idempotent safe re-run (FR-024).

**Checkpoint**: Runs are safe to operate and schedule (spec 11 will add the cron/queue).

---

## Phase 8: Polish & Cross-Cutting

- [X] T053 [P] Migration up+down integrity test in `tests/integration/test_migration_0004.py`.
- [X] T054 [P] Update `docs/RUNBOOK.md` / `docs/DECISIONS.md` with the ingestion run model, source list, and the optional-key note.
- [X] T055 Lint/format gate: `uv run ruff check app worker tests scripts` AND `uv run black --check app worker tests scripts`; confirm every new file ≤ ~300 lines with a one-sentence docstring.
- [X] T056 Confirm coverage: ingestion DB-write paths ≥ 95%, overall suite ≥ 80% (CI gate); add unit tests where short.
- [X] T057 Run `quickstart.md` end-to-end on the live stack (migration up+down, real uvicorn socket, trigger→docs).
- [X] T058 [P] Verify no new **required** Vault secret was introduced (no `.github/workflows/ci.yml` change needed); document the optional keys in `docs/SECURITY.md`.

---

## Dependencies & Execution Order

- **Setup (T001–T003)** → no deps; T002/T003 parallel.
- **Foundational (T004–T015)** → blocks all stories. Within it: T007→T008 (models before migration); T010+T011→T012 (contract+service before runner); T004/T005/T006/T009/T013/T014 are [P].
- **US1 (T016–T022)** → MVP; depends only on Foundational.
- **US2 (T023–T032)** → depends on Foundational + the adapter contract; the five adapters (T026–T030) are [P].
- **US3 (T033–T038)** → depends on Foundational + ≥1 adapter (US1) to produce dupes; refines service/runner.
- **US4 (T039–T045)** → depends on Foundational; touches spec-3 `app/clients/` (additive) — independent of US2/US3.
- **US5 (T046–T052, T059–T061)** → depends on Foundational + runner (US1); refines runner/lifespan. T059–T061 (added by analyze remediation) close FR-022/FR-015/FR-023 test coverage.
- **Polish (T053–T058)** → after all targeted stories.

### Parallel Opportunities

- Setup: T002, T003.
- Foundational: T004, T005, T006, T009, T013, T014 in parallel; then T007→T008, T010→T011→T012, T015.
- US2 adapters: T026–T030 fully parallel (different files), then T031.
- All story test tasks marked [P] run in parallel before their implementation.

## Parallel Example: User Story 2 adapters

```bash
Task: "Implement app/ingestion/adapters/europepmc.py"
Task: "Implement app/ingestion/adapters/openfda.py"
Task: "Implement app/ingestion/adapters/fda_medwatch.py"
Task: "Implement app/ingestion/adapters/ema.py"
Task: "Implement app/ingestion/adapters/mhra.py"
```

## Implementation Strategy

- **MVP** = Setup + Foundational + **US1** (trigger → PubMed → persist → browse → audit). Stop and demo.
- **Incremental**: add US2 (breadth) → US3 (dedup correctness) → US4 (MeSH carryover) → US5 (resilience).
- **Schedule buffer**: EMA/MHRA adapters (T029, T030) are the planned drop-last items if time is short — the spec still demonstrates with PubMed/Europe PMC/openFDA/MedWatch, and the contract makes finishing them additive.
- Commit per task or logical group (Conventional Commits, no Co-Authored-By); keep PRs < 400 lines (adapters may split across PRs).

## Notes

- [P] = different files, no incomplete-task dependency.
- Tests precede implementation within each story; verify they fail first.
- No new container/torch/MCP; one new runtime dep (`httpx`); no new **required** Vault secret.
- Adapters never touch the DB or advance watermarks — persistence/dedup is the runner+service job.
