# Quickstart: Literature Ingestion (validation guide)

**Feature**: 004-literature-ingestion. How to run and validate the feature end-to-end. This is a
run/validate guide — implementation lives in `tasks.md` + the code. See
[dev-environment](../../memory/dev-environment.md) for the toolchain.

## Prerequisites

- The Docker stack up (`docker compose up`) with Vault/Postgres/Redis healthy, and the
  gitignored `docker-compose.override.yml` (ports 5433/6380) on this host.
- Secrets written (`uv run python scripts/write_secrets.py`). **No new required secret** this spec
  — optional `pubmed_api_key` / `openfda_api_key` may be added to Vault to raise rate limits, but
  ingestion works without them.
- Migrations applied through `0004`: `docker compose run --rm api alembic upgrade head`.
- A seeded client + admin (spec 2/3 `scripts/seed_admin.py`, `scripts/seed_client.py`) and at least
  one **active, non-empty** watchlist (spec 3) — ideally with a drug, a keyword, and a MeSH term.

## 1. Validate MeSH save-time validation (US4 / FR-009)

Add MeSH terms to a watchlist (spec-3 endpoint) — one valid (e.g. `Hepatotoxicity`) and one bogus
(e.g. `Notarealmeshterm`). Re-read the watchlist and confirm each MeSH item now carries a
`mesh_validity` (`valid`/`invalid`) and the valid one a `mesh_canonical`. Expected: the bogus term
is saved but flagged `invalid`; nothing is rejected. (With the bundled MeSH artifact removed, terms
read back as `unvalidated` and ingestion still works — FR-009 degradation.)

## 2. Trigger a run (US1 / SC-001, SC-005, SC-008)

`POST /watchlists/{id}/ingest` as the admin → expect **202** with an `IngestionRunOut`
(`status: running`). Confirm:
- a `reviewer` token gets **403**; another client's watchlist gets **404**; an inactive/empty
  watchlist gets **400**.
- exactly one `audit_log` row of type `IngestionRunTriggered` attributed to the admin.

## 3. Inspect run results (US2 / US5 / SC-002, SC-007)

Poll `GET /ingestion-runs/{run_id}` until terminal. Confirm per-source `sources[]` outcomes and
counts; with all sources healthy → `success`; force one source to fail (see §6) → `partial_success`
with that source `failed` and its `error` captured, others unaffected.

## 4. Inspect the corpus & dedup (US2/US3 / SC-002, SC-003, SC-004)

`GET /documents` → documents scoped to your client, each with `source_reliability` and
`contributing_sources`. Confirm:
- a paper present in both PubMed and Europe PMC appears **once** with both in `contributing_sources`
  and the **highest** tier (SC-003 cross-source collapse).
- re-trigger the run with no new external records → the second run's `created` count is 0 and
  `skipped` equals the corpus size (SC-003 re-run).
- another client cannot see these documents (404) (SC-004).

## 5. Validate incremental behavior (FR-021 / SC-010)

After a successful run, check `source_watermarks` advanced for each succeeded source. A second run
fetches only records newer than the watermark (created ≈ 0 when nothing new). Confirm the first run
honored the initial-lookback window (`ingestion_initial_lookback_days`, default 365).

## 6. Validate resilience & interrupted-run recovery (FR-012/FR-024 / SC-007, SC-011)

- **Per-source failure**: in tests, inject a fake adapter that raises → run completes
  `partial_success`, other sources still persist, watermark NOT advanced for the failed source.
- **Interrupted run**: leave a run row in `running` and restart the app → the lifespan startup sweep
  flips it to `failed` with `finished_at` set; a re-trigger creates no duplicates (dedup + watermark).

## Automated checks

```bash
# unit (no stack/network): identifiers, mesh validation, reliability ordering, adapter parsing
uv run pytest tests/unit -q

# integration (needs the live stack; adapters use fakes/recorded fixtures — no live network)
$env:PANTERA_INTEGRATION=1; uv run pytest tests/integration -q

# lint/format — BOTH must pass before commit
uv run ruff check app worker tests scripts
uv run black --check app worker tests scripts
```

**Done when**: all spec acceptance scenarios pass, ingestion DB-write paths ≥ 95% coverage, overall
suite ≥ 80% (CI gate), migration `0004` verified up **and** down, and a real `uvicorn` socket
serves the new endpoints.
