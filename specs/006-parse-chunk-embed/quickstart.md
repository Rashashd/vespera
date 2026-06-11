# Quickstart: Parse, Chunk & Embed — RAG Index Build

Validation/run guide. Implementation details live in `tasks.md`; data shapes in
[data-model.md](./data-model.md) and [contracts/](./contracts/).

## Prerequisites
- Local stack up: `docker compose up` (Postgres **pgvector/pgvector:pg16**, Vault, Redis, api,
  modelserver). Secrets written to Vault (`scripts/write_secrets.py`), including `modelserver_token`.
- Migrations applied through **`0006`**: `uv run alembic upgrade head`.
- Seed: a client + an **active, non-empty** watchlist, then an **ingestion run** so `documents` +
  `document_sources` exist (Spec 4 trigger, or `scripts/seed_client.py`).
- Deps synced: `uv sync` (adds `pgvector`, `lxml`, `tokenizers`).

## Happy path (US1 — make a client's documents searchable)
1. Confirm the embedder is reachable and the version matches:
   `curl -s localhost:8001/ready` → note `models.embedder` version (must equal
   `settings.embedder_model_version`).
2. Trigger a build (staff manager/admin JWT):
   `POST /clients/{client_id}/index` → **202** with an `IndexBuildRunOut` (`status=running`).
3. Poll `GET /clients/{client_id}/index-runs/{run_id}` until `status` ∈ {success, partial_success,
   failed}.
4. **Expected**: every parseable document has ≥1 row in `chunks` with a 768-dim `embedding`, a
   non-empty `text_tsv`, an `embedder_version`, and `ordinal` 0..n-1; each chunk's `client_id` =
   the path client (SC-001, SC-006, SC-008). Documents that parsed to zero chunks show
   `document_index_state.status = indexed_empty`.

## Validation scenarios (map to Success Criteria)
- **Idempotency (SC-003)**: trigger the build again with no new documents → run reports
  `chunks_created = 0` and the modelserver receives **0** `/embed` calls; add one document and
  re-run → exactly that document is parsed/embedded.
- **Isolation (SC-002)**: as a different client's user (or scoped query), confirm **0** of client
  A's chunks are visible under client B.
- **Resilience by cause (SC-004/SC-012)**: seed one malformed payload → it becomes
  `errored_permanent`, the rest index, the run still completes; simulate the modelserver down →
  affected docs become `errored_transient` and a later run indexes them (none lost).
- **Multi-format typing (SC-005)**: with one fixture per source, confirm correct `chunk_type`,
  section labels, tables not split mid-row, figure captions as discrete chunks.
- **No truncation (SC-010)**: across a build, **0** modelserver truncation warnings (chunker uses the
  embedder tokenizer).
- **Concurrency (SC-011)**: fire the trigger twice quickly → one `running` run, **0** duplicate
  chunks.
- **Auth (SC-013)**: a reviewer or client-user calling the trigger → **403**.
- **PII-free logs (SC-007)**: run over a FAERS fixture with de-identified age/sex/country → those
  values appear in **0** log lines.

## Migration check
- `uv run alembic upgrade head` then `uv run alembic downgrade -1` then `upgrade head` again on the
  live DB: `chunks`, `document_index_state`, `index_build_runs` (+ HNSW/GIN/partial-unique indexes)
  create and drop cleanly; the `vector` extension is left in place on downgrade.

## Tests
- `uv run pytest tests/unit -q` (parsers, chunker, tokenizer, selection, failure classification).
- `PANTERA_INTEGRATION=1 uv run pytest tests/integration -q` (build, idempotency, isolation,
  concurrency, auth, no-PII-logs, migration). Lint: `uv run ruff check .` **and**
  `uv run black --check app tests`.
