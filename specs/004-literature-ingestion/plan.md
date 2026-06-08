# Implementation Plan: Literature Ingestion

**Branch**: `004-literature-ingestion` | **Date**: 2026-06-08 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/004-literature-ingestion/spec.md`

## Summary

Reach outside the platform for the first time: given a spec-3 watchlist, fetch new literature and
regulatory safety records from six external sources (PubMed/MeSH, Europe PMC, openFDA FAERS +
drug labels, FDA MedWatch, EMA, MHRA) behind one uniform async adapter contract, normalize each
record to a common shape, **deduplicate per client by a normalized external identifier** (DOI →
PubMed ID → source alert/record id) so one real paper is stored exactly once (contributing
sources recorded, highest reliability tier kept), tag each with a source-reliability tier, and
persist it as a client-scoped `documents` corpus for later specs. Ingestion is **incremental**
against a per-`(watchlist, source)` watermark with a bounded first-run lookback and per-source
cap. An `admin` starts a run via a **manual trigger** that runs as an **in-process background
task** (durable ARQ scheduling is spec 11); runs are tracked, audited, and isolate per-source
failures. This spec also closes the spec-3 carryover by **validating watchlist MeSH terms** at
save time against a bundled slim MeSH list. Backend/API only. Reuses spec-1/2/3 foundations
(async SQLAlchemy + Alembic, the domain-event dispatcher + passive audit handler, the
`require_admin`/`current_active_user` guards, the spec-3 race-safe write pattern) and adds one
Alembic migration, a new `app/ingestion/` package, and exactly one new runtime dependency
(`httpx`).

## Technical Context

**Language/Version**: Python 3.13 (managed by `uv`)

**Primary Dependencies**: FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2, `tenacity`
(reused for retries), fastapi-users (auth guards only). **One new runtime dependency: `httpx`**
(async HTTP client for the source adapters; currently a dev-only dep — promote to runtime).
Metadata extraction uses the **standard-library `xml.etree`** for XML/RSS sources; rich parsing
libs (`lxml`, `xmltodict`, `PyMuPDF`) are deliberately deferred to spec 6. No new container, no
torch, no MCP.

**Storage**: PostgreSQL (existing pgvector image). New tables: `documents`, `document_sources`,
`document_watchlists`, `ingestion_runs`, `ingestion_run_sources`, `source_watermarks`. Additive
columns on `watchlist_items` (`mesh_validity`, `mesh_canonical`). One new migration `0004`.

**Testing**: `uv run pytest` (unit + integration). Adapters are tested against **recorded
fixtures** (no live network in CI); service/integration tests inject fake adapters or stub the
HTTP layer. Integration tests need `PANTERA_INTEGRATION=1` + the live stack
(see [dev-environment](../../memory/dev-environment.md)).

**Target Platform**: Linux container (the `api` service in the existing docker-compose modular
monolith). The reusable run function will later also be callable from the `worker` (spec 11).

**Project Type**: Web service (modular monolith) — backend only this spec.

**Performance Goals**: Not throughput-bound. A run fans out to ≤7 source adapters concurrently
(`asyncio.gather`) with bounded per-source concurrency and a per-source result cap (default 200);
each external call has a timeout + ≤3 backed-off retries. No p95 target beyond "a manual run
completes in seconds-to-low-minutes and never blocks the trigger request" (background task).

**Constraints**: Async throughout (`httpx.AsyncClient`, no `requests`/`time.sleep`); Pydantic
boundaries (no ORM leakage); `structlog` with `client_id` bound and **no PII/secret in logs**;
every external call wrapped in `tenacity` (no retry on 4xx); files ≤ ~300 lines with a
one-sentence docstring; ingestion DB-write paths ≥ 95% line coverage, overall suite ≥ 80%
(CI gate).

**Scale/Scope**: Small-to-moderate. Tens of watchlists per client; per-source cap bounds a run's
fetch volume; the corpus grows over time but each run is incremental.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Relevance | Status |
|-----------|-----------|--------|
| I. Human-in-the-Loop | No drafting/sending here; ingestion only persists raw records | ✅ N/A |
| II. Grounding | No reports/claims here; this builds the corpus later grounding draws on | ✅ N/A |
| III. Triage Fails Safe | No triage here; source-reliability tier is captured for later safe triage | ✅ N/A (enabling) |
| IV. Backed by a Number | No model/eval; the 95% write-path + 80% overall coverage gates apply; dedup/incremental asserted by SC-003/010/011 | ✅ Aligned |
| V. Multi-Tenant Isolation (NON-NEGOTIABLE) | Every new table carries `client_id` and is indexed; all reads/writes client-scoped; trigger + browse refuse cross-tenant; dedup is **per client** (no cross-client document sharing) | ✅ Enforced |
| VI. Lean, Reproducible, Justified | One justified new runtime dep (`httpx`); stdlib XML to avoid pulling spec-6 parsers early; no new container/torch/MCP; one new package + one migration | ✅ Aligned |
| VII. Own Every Line (Spec-Driven) | spec → clarify → checklist → plan → tasks → implement; Conventional Commits; PR < 400 lines (may split adapters across PRs) | ✅ Aligned |

**Engineering standards applied**: async routes/adapters with `httpx.AsyncClient`;
`asyncio.gather` for the multi-source fan-out, `asyncio.Semaphore` for per-source politeness;
**`tenacity`** retry (stop_after_attempt(3), exponential backoff, retry only timeouts/5xx, never
4xx) on every external call; Pydantic schemas at the boundary; small enums as `String` + CHECK
mirrored by `StrEnum` (spec-3 pattern); race-safe writes via `INSERT … ON CONFLICT` + savepoint
flush (spec-3 `_try_flush`); audit rows written in the same transaction via the dispatcher;
`structlog` binds `client_id`/`run_id` and never logs payloads/PII/secrets.

**External-call security note (tracked deferral, not a violation)**: The constitution requires
the NeMo Guardrails sidecar on **external/LLM-facing** calls. This spec's external calls are
**outbound fetches** of public literature; none feed an LLM here. Injection scanning of ingested
text (NeMo) and PII/secret redaction (Presidio) interpose in **spec 12**, before the corpus is
ever parsed/embedded or reaches the agent (FR-018/FR-023). This spec stores raw records faithfully
and keeps PII out of logs.

**Result**: PASS — no violations. Complexity Tracking table intentionally empty.

## Project Structure

### Documentation (this feature)

```text
specs/004-literature-ingestion/
├── plan.md              # This file
├── research.md          # Phase 0 output (design decisions D1–D16)
├── data-model.md        # Phase 1 output (tables, enums, relationships)
├── quickstart.md        # Phase 1 output (run/validate guide)
├── contracts/           # Phase 1 output
│   ├── ingestion-runs.md   # trigger + run-status endpoints
│   ├── documents.md        # document browse endpoints
│   └── source-adapter.md   # the internal uniform adapter contract
├── checklists/
│   ├── requirements.md     # spec-quality gate (from /speckit-specify)
│   └── ingestion.md        # requirements QA (from /speckit-checklist)
└── tasks.md             # /speckit-tasks output (NOT created here)
```

### Source Code (repository root)

New self-contained `app/ingestion/` package (mirrors `app/clients/`), one Alembic migration, an
additive change to the spec-3 watchlist write path (save-time MeSH validation), a startup hook to
reconcile interrupted runs, and tests. No other existing modules change except additive event
classes, router registration, the `Settings` additions, and the lifespan startup sweep.

```text
app/
├── ingestion/                       # NEW package owned by this spec
│   ├── __init__.py
│   ├── enums.py                     # SourceName, SourceReliability(+rank), IngestionRunStatus,
│   │                                #   SourceRunStatus, MeshValidity
│   ├── models.py                    # documents, document_sources, document_watchlists,
│   │                                #   ingestion_runs, ingestion_run_sources, source_watermarks
│   ├── schemas.py                   # Pydantic request/response (no ORM leakage)
│   ├── identifiers.py               # normalized-identifier precedence (DOI→PMID→alert id) (pure)
│   ├── mesh.py                      # bundled slim-list loader + validate()/resolve() (pure-ish)
│   ├── data/
│   │   └── mesh_terms.txt           # bundled slim MeSH heading list (canonical term per line)
│   ├── adapters/
│   │   ├── __init__.py              # SourceAdapter protocol + RawRecord + enabled-adapter registry
│   │   ├── pubmed.py                # E-utilities esearch/efetch + MeSH targeting (stdlib XML)
│   │   ├── europepmc.py             # Europe PMC REST (JSON)
│   │   ├── openfda.py               # FAERS + drug-label endpoints (JSON) → two SourceNames
│   │   ├── fda_medwatch.py          # MedWatch alert feed (RSS/XML, stdlib)
│   │   ├── ema.py                   # EMA safety feed (sequenced last)
│   │   └── mhra.py                  # MHRA drug-safety feed (sequenced last)
│   ├── runner.py                    # run_ingestion(): fan-out, per-source isolation, dedup, counts
│   ├── service.py                   # persistence (dedup upsert, provenance, watermark, run record)
│   ├── routes_ingestion.py          # POST /watchlists/{id}/ingest ; GET runs
│   └── routes_documents.py          # GET /documents ; GET /documents/{id}
├── infra/
│   └── http.py                      # NEW shared httpx.AsyncClient factory + tenacity retry helper
├── clients/
│   ├── routes_watchlists.py         # MODIFY: call MeSH validator on add/edit of a mesh item
│   └── service.py                   # MODIFY: persist mesh_validity/mesh_canonical on item write
├── core/
│   ├── config.py                    # ADD: optional source keys + lookback/cap settings (non-secret)
│   └── lifespan.py                  # ADD: verify bundled MeSH artifact; reconcile running→failed
├── domain/events.py                 # ADD IngestionRunTriggered (auto-audited)
├── db/migrations/versions/
│   └── 0004_ingestion.py            # NEW: 6 tables + indexes + watchlist_items mesh columns
└── main.py                          # ADD include_router(ingestion_router, documents_router)

tests/
├── unit/
│   ├── test_identifiers.py          # normalization precedence + namespacing (pure)
│   ├── test_mesh_validation.py      # valid/invalid/unvalidated; missing-artifact degradation
│   ├── test_reliability.py          # tier ordering + highest-contributing resolution
│   └── test_adapters_parsing.py     # each adapter normalizes recorded fixtures → RawRecord
└── integration/
    ├── test_ingest_trigger.py       # trigger authz, eligibility, background run, counts
    ├── test_ingest_dedup.py         # re-run zero-dupes; cross-source collapse; per-client isolation
    ├── test_ingest_incremental.py   # watermark advance on success; first-run lookback (SC-010)
    ├── test_ingest_resilience.py    # per-source failure isolation; partial_success; interrupted→failed
    ├── test_documents_api.py        # browse scoping; admin/reviewer; cross-tenant refusal
    ├── test_mesh_savetime.py        # save-time validation on the watchlist write path
    └── test_migration_0004.py       # upgrade/downgrade integrity
```

**Structure Decision**: Follow the spec-2/spec-3 precedent — a self-contained feature package
under `app/ingestion/` with `models`/`schemas`/`service`/`routes_*`, thin routers delegating to a
`service.py`, pure helpers isolated (`identifiers.py`, `mesh.py`), and one additive Alembic
migration. The six adapters live behind one `SourceAdapter` contract in `adapters/`, exercised by
a single `runner.run_ingestion()` that is **framework-agnostic and directly callable in tests** so
spec 11 can enqueue it on ARQ unchanged. Save-time MeSH validation is an additive enhancement to
the spec-3 watchlist write path (the carryover spec 3 explicitly deferred here). EMA/MHRA adapters
are implemented last per the spec's schedule-risk sequencing, behind the now-proven contract.

## Complexity Tracking

> No constitution violations — table intentionally empty. (The single new runtime dependency
> `httpx` is the standard async HTTP client and is justified under Principle VI; richer parsers
> are deferred to spec 6 to keep this slice lean.)
