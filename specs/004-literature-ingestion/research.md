# Research & Design Decisions: Literature Ingestion

**Feature**: 004-literature-ingestion · **Date**: 2026-06-08

All spec ambiguities were resolved in two `/speckit-clarify` sessions (see spec.md §Clarifications)
and a checklist-driven hardening pass. This file records the implementation-level decisions and
their rationale. No `NEEDS CLARIFICATION` markers remain.

---

## D1 — Package layout

**Decision**: A new self-contained `app/ingestion/` package mirroring `app/clients/`
(`models`/`schemas`/`service`/`routes_*`), with adapters under `app/ingestion/adapters/` and pure
helpers (`identifiers.py`, `mesh.py`) split out for unit-testability.
**Rationale**: Matches the spec-2/spec-3 precedent (reviewable, ≤300-line files, thin routes).
**Alternatives**: A single `ingestion.py` (rejected: far exceeds the file-size rule); putting
adapters in `app/infra/` (rejected: they are domain logic, not generic infrastructure).

## D2 — Database tables

**Decision**: Six new tables (all carry `client_id`, all indexed on it):
`documents`, `document_sources`, `document_watchlists`, `ingestion_runs`,
`ingestion_run_sources`, `source_watermarks`; plus two additive columns on `watchlist_items`.
A document is one real paper per client; per-source provenance and per-watchlist provenance are
separate child tables so a shared paper is stored once. See [data-model.md](./data-model.md).
**Rationale**: The clarified data model (cross-source dedup, contributing sources, watchlist
provenance, per-(watchlist,source) watermark, per-source run outcomes) needs normalized child
tables, not JSON blobs, so dedup and counts are enforceable at the DB layer.
**Alternatives**: Single `documents` row with JSON `sources`/`watchlists` arrays (rejected: can't
enforce uniqueness or query provenance; spec-3 favored real columns + CHECK over JSON enums).

## D3 — Enums (String + CHECK, mirrored by StrEnum)

**Decision**: In `app/ingestion/enums.py`, following the spec-3 `clients/enums.py` pattern:
- `SourceName`: `pubmed`, `europepmc`, `openfda_faers`, `openfda_label`, `fda_medwatch`, `ema`, `mhra`
- `SourceReliability`: `regulatory_alert` > `peer_reviewed` > `preprint` > `case_report` with a
  `.rank` property (mirrors `SeverityLevel.rank`) so "highest contributing tier" is a `max()`
- `IngestionRunStatus`: `running`, `success`, `partial_success`, `failed`
- `SourceRunStatus`: `success`, `failed` (per-source outcome within a run)
- `MeshValidity`: `valid`, `invalid`, `unvalidated`
**Rationale**: Consistency with the established CHECK-constraint pattern; ordering encoded once.
**Alternatives**: Postgres native `ENUM` types (rejected: spec-3 chose String+CHECK for simpler
migrations and StrEnum mirroring).

## D4 — Normalized external identifier

**Decision**: `identifiers.py` produces a namespaced string by precedence **DOI → PubMed ID →
source-native alert/record id**: `doi:10.1000/xyz`, else `pmid:123456`, else
`<source>:<native-id>` (e.g., `fda_medwatch:2026-abc`). DOIs are lowercased and stripped of any
`https://doi.org/` prefix. This string is the dedup key (`documents.normalized_external_id`,
unique per `client_id`). A record exposing none of these and no stable source key is **errored**,
never stored (FR-006/FR-014).
**Rationale**: DOI is the most cross-source-stable identifier (shared by PubMed + Europe PMC),
making the cross-source collapse (clarification pass 2) reliable; namespacing prevents accidental
collisions between identifier spaces.
**Alternatives**: Hashing title+authors (rejected: brittle, false merges); keeping source in the
key (rejected: defeats cross-source dedup, the explicit clarified requirement).

## D5 — Uniform adapter contract

**Decision**: `adapters/__init__.py` defines a `SourceAdapter` `Protocol` and a frozen `RawRecord`
dataclass. Each adapter exposes `name: SourceName`, `reliability: SourceReliability`, and
`async def fetch(query, since, cap) -> list[RawRecord]`. A module-level registry lists the enabled
adapters; the runner iterates it. See [contracts/source-adapter.md](./contracts/source-adapter.md).
**Rationale**: One contract makes adding/removing a source require no document-shape change
(FR-003), enables the EMA/MHRA "sequenced last" plan, and lets tests inject fakes.
**Alternatives**: Per-source bespoke functions (rejected: no uniform fan-out, harder to test).

## D6 — HTTP client + retries (`app/infra/http.py`)

**Decision**: A shared `httpx.AsyncClient` factory (sane timeouts, a descriptive User-Agent incl.
contact email per NCBI etiquette) plus a `tenacity` retry helper:
`stop_after_attempt(3)`, exponential backoff, retry only on timeouts/connection errors/HTTP 5xx,
**never on 4xx**. Per-source concurrency bounded by an `asyncio.Semaphore`. Promote `httpx` from
dev to runtime dependencies in `pyproject.toml`.
**Rationale**: Constitution: async + `tenacity` on every external call, no SDK-internal retries.
One shared helper keeps retry/observability uniform across six adapters.
**Alternatives**: `requests` (forbidden — sync); SDK-built-in retries (rejected — constitution).

## D7 — External-source credentials (Vault, all OPTIONAL)

**Decision**: Add **optional** secret fields to `Settings`, populated from Vault if present and
left empty otherwise: `pubmed_api_key`, `openfda_api_key`. Add a **non-secret** setting
`ncbi_tool_email` for E-utilities etiquette. None is added to `_REQUIRED_SECRETS`, so there is
**no new required Vault secret and no CI secret-writer change** (matching spec-3). PubMed/openFDA
function key-less at lower rate limits; a present key simply raises limits. (A *required* missing
credential would degrade that source to a recorded failure per FR-017, but none here is required.)
**Rationale**: Keeps the spec's "no new required secret" posture while supporting higher limits;
avoids the spec-2 CI fail-fast trap by not making them mandatory.
**Alternatives**: Mandatory keys (rejected: the public APIs work without them; would force a CI
secret + risk fail-fast).

## D8 — Execution model: in-process background task + startup reconciliation

**Decision**: `POST /watchlists/{id}/ingest` validates eligibility/authz, **creates the
`ingestion_runs` row with status `running`**, schedules `runner.run_ingestion(run_id, …)` via
FastAPI `BackgroundTasks`, and returns the run id immediately (HTTP 202). The runner updates the
run to a terminal status on completion. On lifespan **startup**, a sweep reconciles any run still
`running` (orphaned by a prior process stop) to `failed` (FR-024). `run_ingestion` takes a
session-factory, not a request session, so it is reusable by spec-11's ARQ worker unchanged.
**Rationale**: Clarification pass 1 chose background-task (avoids request timeouts; keeps ARQ
orchestration in spec 11). The startup sweep makes the non-durable model honest (no perpetual
`running`).
**Alternatives**: Synchronous inline run (rejected: timeout risk); enqueue to ARQ now (rejected:
that machinery is spec 11).

## D9 — Incremental windowing

**Decision**: `source_watermarks(watchlist_id, source)` stores the high-water mark = the max
record date successfully ingested for that pair. A run fetches `since = watermark` (or
`now − initial_lookback` on first run) up to `per_source_cap` records, and advances the watermark
**only if that source succeeded**. New non-secret settings: `ingestion_initial_lookback_days`
(default 365) and `ingestion_per_source_cap` (default 200). "Newer" is measured on the record's
publication/alert date, falling back to the source's indexed date; a source with **no usable
date** is paged by its native cursor and relies on dedup to suppress repeats (FR-021).
**Rationale**: Standard incremental-monitoring pattern; per-pair watermark + success-gated advance
gives correct retry-after-failure semantics (FR-012/FR-021); caps bound runaway fetches.
**Alternatives**: Fixed lookback every run (rejected pass 2); full backfill (rejected pass 2).

## D10 — Dedup write path (race-safe)

**Decision**: Reuse the spec-3 race-safe pattern. Per normalized record:
`INSERT INTO documents … ON CONFLICT (client_id, normalized_external_id) DO NOTHING`, then select
the row (existing or new); upsert the `document_sources` row (`ON CONFLICT (document_id, source)
DO NOTHING`); recompute `documents.source_reliability` as the **max rank** across its
`document_sources`; upsert the `document_watchlists` provenance row. Concurrent overlapping runs
are safe because the unique index is the real guard (spec-3 `_try_flush`/savepoint).
**Rationale**: Guarantees "one paper per client" under concurrency (FR-006, Edge: concurrent
triggers); keeps counts (created vs skipped) accurate.
**Alternatives**: Read-then-write without ON CONFLICT (rejected: race window → duplicates/500s).

## D11 — Bundled MeSH validation

**Decision**: Ship `app/ingestion/data/mesh_terms.txt` — a slim list of canonical MeSH descriptor
terms (one per line, lowercased), a few MB, generated from the public MeSH descriptor file by an
operator script (the generation is an out-of-band op task; the artifact is committed). `mesh.py`
loads it into a frozenset at startup (cached on `app.state`), exposes
`validate(term) -> (MeshValidity, canonical|None)`. Lifespan **verifies the artifact exists** at
startup; if missing/unreadable, terms are marked `unvalidated` and ingestion still proceeds on
drugs/keywords (FR-009) — non-fatal, unlike the model-hash startup gate.
**Rationale**: Clarification pass 1 chose a bundled slim list (offline, deterministic, CI-testable,
lightweight); PubMed performs synonym **expansion** server-side, so no expansion engine is built.
**Alternatives**: Live NLM lookup (rejected pass 1: external dep + must mock); full descriptor tree
(rejected: hundreds of MB).

## D12 — Save-time MeSH validation on the spec-3 write path

**Decision**: Enhance `app/clients` watchlist item add/edit so that when an item of type `mesh` is
written, the service calls `mesh.validate()` and persists `watchlist_items.mesh_validity` +
`mesh_canonical`. Validation **flags, never blocks** (invalid terms are saved and marked). The
ingestion run **re-checks defensively** before PubMed targeting. Non-mesh items leave the columns
null.
**Rationale**: Clarification pass 1 chose save-time validation so validity is visible on every
watchlist read; spec 3 explicitly deferred this here, so touching that path is expected.
**Alternatives**: Validate only at run time (rejected pass 1: no immediate feedback).

## D13 — API surface

**Decision** (all client-scoped via `current_active_user`; trigger gated by `require_admin`):
- `POST /watchlists/{watchlist_id}/ingest` → 202, returns the new run (admin).
- `GET /watchlists/{watchlist_id}/ingestion-runs` → list runs (admin + reviewer view).
- `GET /ingestion-runs/{run_id}` → run detail incl. per-source outcomes (admin + reviewer).
- `GET /documents` (filterable by `watchlist_id`, `source`, `reliability`) → client's corpus.
- `GET /documents/{document_id}` → document detail incl. contributing sources + provenance.
See [contracts/](./contracts/).
**Rationale**: Mirrors spec-3 routing; admin writes / reviewer reads (FR-008). Trigger nested under
the watchlist; documents/runs are first-class read resources.
**Alternatives**: A single `/ingest` taking a body (rejected: nesting under the watchlist is
clearer and matches spec-3 scoping).

## D14 — Domain event & audit

**Decision**: Add `IngestionRunTriggered(DomainEvent)` (fields: `watchlist_id`, `run_id`) raised
once per trigger; auto-audited via the existing `register_audit_handlers` subclass walk. Add a
`("run_id", "ingestion_run")` (and `watchlist_id`) target mapping in `audit/handler._target_for`.
**Rationale**: FR-016/SC-008 (one audit row per trigger, attributed to the admin) reusing the
spec-2/3 dispatcher; no new audit machinery.
**Alternatives**: Auditing run completion too (rejected: trigger is the human action; completion is
system-driven and captured in the run record).

## D15 — Migration 0004

**Decision**: One `0004_ingestion.py` creating the six tables + indexes (incl. the unique
`(client_id, normalized_external_id)` and `(watchlist_id, source)` watermark index) and adding
`watchlist_items.mesh_validity` (nullable, CHECK in {valid,invalid,unvalidated}) + `mesh_canonical`
(nullable). Downgrade drops the columns and tables. Does not alter spec-1/2/3 data.
**Rationale**: Additive, reversible, follows `app/db/CONVENTIONS.md`; verified up+down in CI/local.
**Alternatives**: Splitting into multiple migrations (unnecessary; one logical unit).

## D16 — Testing strategy (no live network in CI)

**Decision**: Each adapter ships recorded sample payloads under `tests/fixtures/<source>/`; unit
tests assert each adapter normalizes its fixture into the expected `RawRecord`. Service/integration
tests inject **fake adapters** (returning canned `RawRecord`s) into the runner, so dedup,
incremental, resilience, counts, and authz are tested deterministically without network. A
`partial_success` test makes one fake adapter raise; an interrupted-run test asserts the startup
sweep flips `running → failed` and a re-run creates no duplicates.
**Rationale**: Constitution IV/coverage gates + fresh-clone smoke; adapters must be CI-safe.
**Alternatives**: Live API calls in CI (rejected: flaky, rate-limited, non-deterministic).
