# Data Model: Literature Ingestion

**Feature**: 004-literature-ingestion · **Date**: 2026-06-08 · **Migration**: `0004_ingestion.py`

All tables carry `client_id` and are indexed on it (Constitution V). Enums are `String` columns
with CHECK constraints, mirrored by `StrEnum`s in `app/ingestion/enums.py` (spec-3 pattern).
Money/dates: timezone-aware `DateTime`. Raw payloads: `JSONB`.

## Enums (`app/ingestion/enums.py`)

| Enum | Values | Notes |
|------|--------|-------|
| `SourceName` | `pubmed`, `europepmc`, `openfda_faers`, `openfda_label`, `fda_medwatch`, `ema`, `mhra` | the configured sources |
| `SourceReliability` | `regulatory_alert` > `peer_reviewed` > `preprint` > `case_report` | ordered; `.rank` (3→0) → "highest" = `max(rank)` |
| `IngestionRunStatus` | `running`, `success`, `partial_success`, `failed` | FR-011 |
| `SourceRunStatus` | `success`, `failed` | per-source outcome in a run |
| `MeshValidity` | `valid`, `invalid`, `unvalidated` | `unvalidated` when bundled artifact absent (FR-009) |

## Tables

### `documents` — one real paper/record per client (dedup target)

| Column | Type | Notes |
|--------|------|-------|
| `id` | BigInteger PK | |
| `client_id` | BigInteger, FK `clients.id`, not null | tenant scope |
| `normalized_external_id` | String(512), not null | dedup key (D4): `doi:…` / `pmid:…` / `<source>:<id>` |
| `source_reliability` | String(20), not null | **highest** tier across `document_sources` (FR-005) |
| `title` | String(1024), nullable | optional (FR-004) |
| `summary` | Text, nullable | abstract/summary if provided (optional) |
| `published_at` | DateTime(tz), nullable | publication/alert date (optional; drives watermark) |
| `origin_url` | String(2048), nullable | optional |
| `first_fetched_at` | DateTime(tz), not null, default now | |
| `last_fetched_at` | DateTime(tz), not null, default now, onupdate now | bumped when re-seen |

**Constraints/Indexes**: `ck_documents_reliability` CHECK in the 4 tiers;
`ux_documents_client_extid` UNIQUE `(client_id, normalized_external_id)` ← the dedup guard;
`ix_documents_client_id`; `ix_documents_client_reliability (client_id, source_reliability)`.

### `document_sources` — contributing source(s) of a document (1 document → N sources)

| Column | Type | Notes |
|--------|------|-------|
| `id` | BigInteger PK | |
| `document_id` | BigInteger, FK `documents.id` ON DELETE CASCADE, not null | |
| `client_id` | BigInteger, not null | tenant scope (denormalized for scoped queries) |
| `source` | String(20), not null | `SourceName` |
| `source_external_id` | String(512), not null | the id as that source reported it (e.g., raw PMID) |
| `source_reliability` | String(20), not null | this source's tier |
| `raw_payload` | JSONB, not null | faithful raw record for spec-6 parsing (FR-004/FR-023) |
| `fetched_at` | DateTime(tz), not null, default now | |

**Constraints/Indexes**: `ck_document_sources_source` CHECK in `SourceName`;
`ck_document_sources_reliability` CHECK in tiers;
`ux_document_sources_doc_source` UNIQUE `(document_id, source)` (one row per source per document);
`ix_document_sources_client_id`.

### `document_watchlists` — provenance: which watchlist(s)/run surfaced the document

| Column | Type | Notes |
|--------|------|-------|
| `id` | BigInteger PK | |
| `document_id` | BigInteger, FK `documents.id` ON DELETE CASCADE, not null | |
| `watchlist_id` | BigInteger, FK `watchlists.id` ON DELETE CASCADE, not null | |
| `client_id` | BigInteger, not null | tenant scope |
| `first_run_id` | BigInteger, FK `ingestion_runs.id`, nullable | run that first linked it |
| `created_at` | DateTime(tz), not null, default now | |

**Constraints/Indexes**: `ux_document_watchlists_doc_wl` UNIQUE `(document_id, watchlist_id)`
(idempotent provenance — within-client many-to-many); `ix_document_watchlists_watchlist_id`;
`ix_document_watchlists_client_id`.

### `ingestion_runs` — a tracked unit of ingestion work for one watchlist

| Column | Type | Notes |
|--------|------|-------|
| `id` | BigInteger PK | |
| `client_id` | BigInteger, FK `clients.id`, not null | |
| `watchlist_id` | BigInteger, FK `watchlists.id`, not null | |
| `triggered_by_user_id` | BigInteger, FK `users.id`, not null | the acting admin |
| `status` | String(16), not null, default `running` | `IngestionRunStatus` (FR-011, FR-024) |
| `started_at` | DateTime(tz), not null, default now | |
| `finished_at` | DateTime(tz), nullable | set on terminal status |
| `fetched_count` | Integer, not null, default 0 | run totals (sum of per-source) |
| `created_count` | Integer, not null, default 0 | |
| `skipped_count` | Integer, not null, default 0 | duplicates skipped |
| `errored_count` | Integer, not null, default 0 | unnormalizable records |

**Constraints/Indexes**: `ck_ingestion_runs_status` CHECK in the 4 statuses;
`ix_ingestion_runs_client_id`; `ix_ingestion_runs_watchlist_id`;
`ix_ingestion_runs_status` (for the startup `running→failed` sweep).

### `ingestion_run_sources` — per-source outcome within a run

| Column | Type | Notes |
|--------|------|-------|
| `id` | BigInteger PK | |
| `run_id` | BigInteger, FK `ingestion_runs.id` ON DELETE CASCADE, not null | |
| `client_id` | BigInteger, not null | tenant scope |
| `source` | String(20), not null | `SourceName` |
| `status` | String(16), not null | `SourceRunStatus` |
| `error` | Text, nullable | captured failure reason (FR-012) |
| `fetched_count` / `created_count` / `skipped_count` / `errored_count` | Integer, not null, default 0 | |

**Constraints/Indexes**: `ck_ingestion_run_sources_source` / `_status` CHECKs;
`ux_ingestion_run_sources_run_source` UNIQUE `(run_id, source)`; `ix_…_client_id`.

### `source_watermarks` — per-(watchlist, source) incremental high-water mark

| Column | Type | Notes |
|--------|------|-------|
| `id` | BigInteger PK | |
| `client_id` | BigInteger, not null | tenant scope |
| `watchlist_id` | BigInteger, FK `watchlists.id` ON DELETE CASCADE, not null | |
| `source` | String(20), not null | `SourceName` |
| `watermark_at` | DateTime(tz), nullable | max record date ingested; null ⇒ first run uses lookback |
| `cursor` | String(512), nullable | for dateless sources (D9) |
| `updated_at` | DateTime(tz), not null, default now, onupdate now | advanced only on source success |

**Constraints/Indexes**: `ck_source_watermarks_source` CHECK;
`ux_source_watermarks_wl_source` UNIQUE `(watchlist_id, source)`; `ix_…_client_id`.

### `watchlist_items` — ADDITIVE columns (spec-3 table)

| Column | Type | Notes |
|--------|------|-------|
| `mesh_validity` | String(12), nullable | `MeshValidity` for `item_type='mesh'`; null otherwise |
| `mesh_canonical` | String(512), nullable | resolved canonical heading when `valid` |

**Constraint**: `ck_watchlist_items_mesh_validity` CHECK `mesh_validity IS NULL OR mesh_validity IN
('valid','invalid','unvalidated')`.

## Relationships

```
clients (spec 3) ──1:N── documents ──1:N── document_sources        (contributing sources)
                              │
                              ├──1:N── document_watchlists ──N:1── watchlists (spec 3)   (provenance)
                              │
watchlists ──1:N── ingestion_runs ──1:N── ingestion_run_sources    (per-source outcome)
watchlists ──1:N── source_watermarks                               (per (watchlist, source))
users (spec 2) ──1:N── ingestion_runs.triggered_by_user_id         (audit actor)
watchlist_items (spec 3) + mesh_validity/mesh_canonical            (save-time MeSH validation)
```

## Validation & state rules (from requirements)

- **Dedup (FR-006, D4/D10)**: uniqueness enforced by `ux_documents_client_extid`. Re-seen record →
  no new `documents` row; add `document_sources`/`document_watchlists` rows; recompute
  `documents.source_reliability = max(rank)`; bump `last_fetched_at`.
- **Reliability (FR-005)**: `documents.source_reliability` = highest-rank tier among its
  `document_sources` rows.
- **Run status (FR-011, FR-024)**: `success` = all attempted sources `success`; `partial_success`
  = ≥1 success and ≥1 failed; `failed` = all failed / could not start. Startup sweep flips any
  lingering `running` → `failed` with `finished_at = now`.
- **Watermark (FR-021)**: advanced to the max `published_at` ingested for a source **only** when
  that source's `SourceRunStatus = success`.
- **Empty/ineligible (FR-001)**: trigger refused for deactivated/empty/other-client/non-existent
  watchlist; no rows written.
- **Unidentifiable record (FR-006/FR-014)**: increments `errored_count`, never stored.
- **MeSH validity (FR-009, D11/D12)**: set at save time for mesh items; `unvalidated` when the
  bundled artifact is unavailable; re-checked defensively at run time; flags never block.
