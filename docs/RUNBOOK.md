# RUNBOOK

Operational guide for running Pantera locally and in production.

## Local (Docker Compose)

1. `cp .env.example .env` (only `VAULT_ADDR` / `VAULT_TOKEN`; no real secrets).
2. `docker compose up -d vault postgres redis`
3. Write secrets into Vault once. `scripts/write_secrets.py` is a **local-only helper**
   (gitignored — not in a fresh clone). If present:
   `ANTHROPIC_API_KEY=... uv run python scripts/write_secrets.py`
   Otherwise write them with the Vault CLI:
   `docker compose exec -e VAULT_TOKEN=root vault vault kv put secret/pantera/secrets \
     database_url='postgresql+asyncpg://pantera:pantera@postgres:5432/pantera' \
     redis_url='redis://redis:6379/0' anthropic_api_key='<key>'`
4. Apply the baseline schema (in-container so hostnames resolve):
   `docker compose run --rm api alembic upgrade head`
5. `docker compose up -d` — then `curl http://localhost:8000/health` → `{"status":"ok"}`.
6. **Bootstrap the first admin** (spec 2; idempotent — a no-op if any user exists):
   `docker compose run --rm api python scripts/seed_admin.py`
   It reads `bootstrap_admin_email` / `bootstrap_admin_password` from Vault (defaults
   `admin@pantera.io` / `ChangeMe1!`; override via env before `write_secrets.py`, and change
   the password after first login). Use a deliverable email domain — `.local` is rejected.

## Authentication (spec 2)

- Log in: `POST /auth/jwt/login` (form `username`=email, `password`) → `{access_token,
  token_type:"bearer"}`. Send the token as `Authorization: Bearer <token>` on protected routes.
- Tokens are stateless JWTs (~30 min, no refresh); deactivating a user takes effect within one
  token lifetime. The signing key is the Vault secret `auth_jwt_secret` (required at boot).
- Login is rate-limited to **5/min per source IP** (429 when exceeded); there is no per-account
  lockout by design.
- Admin-only user management: `POST /users`, `GET /users`, `PATCH /users/{id}` — all scoped to
  the admin's `client_id`.

## Clients & watchlists (spec 3)

Tenant onboarding is an **operator script** (not an API), mirroring `seed_admin.py` — this avoids
an admin suspending their own client and locking themselves out. Migration `0003` also reconciles
every pre-existing `users.client_id` into a real `clients` row (named `Client <id>`) and adds the
`users.client_id → clients.id` foreign key.

- Create a client: `docker compose run --rm api python scripts/seed_client.py --name "Acme Pharma"`
  → prints the new client id. Duplicate names (case-insensitive) are rejected.
- Suspend / reactivate: `... scripts/seed_client.py --suspend <id>` / `--activate <id>`. No
  destructive delete — suspension only. Each action writes one audit row (system actor).

Client API (the caller only ever sees its **own** client; `client_id` comes from the token):

- `GET /clients/me` — read your client (any active user).
- `PATCH /clients/me {"name": "..."}` — rename your client (admin only; `status` is operator-only).

Watchlist API (base `/watchlists`; **writes require admin**, reads allow reviewer; everything is
client-scoped and a cross-tenant id returns 404):

- `POST /watchlists` — create a named watchlist with ≥1 item (`items: [{item_type, value}]`,
  `item_type ∈ drug|mesh|keyword`). Empty ⇒ 400 `WATCHLIST_EMPTY`; duplicate name ⇒ 409.
  Optional `cadence` (`daily|weekly|monthly`, default `weekly`), `severity_threshold`
  (`non-serious|serious|life-threatening`, default `serious`), `budget_amount` (≥0, null = no cap).
- `GET /watchlists` (`?include_inactive=true`), `GET /watchlists/{id}`.
- `PATCH /watchlists/{id}` — rename / set cadence,severity,budget / `is_active`. Deactivation is a
  **soft delete** (data preserved, excluded from monitoring).
- `POST /watchlists/{id}/items` (idempotent: 201 created, 200 duplicate no-op),
  `DELETE /watchlists/{id}/items/{item_id}` (graceful; refuses to empty an active watchlist).

Each watchlist read exposes a derived `budget_status` (`ok` < 80% → `warning` ≥ 80% →
`soft_capped` ≥ 100% of the current-UTC-month spend) and `current_period_spend`. Raising the
budget or a new month auto-clears the cap (spend metering itself arrives in a later spec).

## Literature ingestion (spec 4)

### Run model

An ingestion run is triggered via `POST /watchlists/{id}/ingest` (admin only). It fans out
concurrently across up to six source adapters (PubMed, Europe PMC, openFDA FAERS, openFDA Labels,
FDA MedWatch, EMA, MHRA). Each adapter is isolated: one failure → `partial_success`; all fail →
`failed`. Records are deduplicated per client by normalized external ID (DOI > PMID > source:id).

Run status is readable immediately via `GET /ingestion-runs/{id}`. The background task
updates it to `success`, `partial_success`, or `failed` when complete.

### Optional API keys

Two Vault secrets are **optional** (not required for boot): `pubmed_api_key` and
`openfda_api_key`. Without them the adapters use the unauthenticated rate-limited tier.
Add them to Vault if you hit 429 errors on those endpoints:
```
vault kv patch secret/pantera/secrets pubmed_api_key='<key>' openfda_api_key='<key>'
```

### MeSH validation

MeSH terms are validated at watchlist write time against the bundled slim heading list at
`app/ingestion/data/mesh_terms.txt`. Validity is stored per item (`mesh_validity`: `valid` |
`invalid` | `unvalidated`). Invalid terms are flagged but never rejected. The runner excludes
confirmed-invalid terms from PubMed MeSH targeting.

To regenerate the list from the full NLM distribution: `scripts/generate_mesh_list.py` (not
committed; see that file for operator instructions).

### Source watermarks

Each `(watchlist_id, source)` pair has a watermark (`source_watermarks` table). The first run
uses a lookback of `ingestion_initial_lookback_days` (default 365). Subsequent runs use the
watermark from the previous successful run. Watermarks are only advanced on source success.

### Startup reconciliation

At startup the app sweeps any runs stuck in `running` (from a crash) and marks them `failed`.
This is idempotent and safe for re-runs.

## Startup behavior

- The app loads secrets from Vault first and **refuses to boot** if Vault, Postgres, or
  Redis is unavailable, or if a required secret is missing.
- At startup: MeSH artifact check (non-fatal warning if missing) and stale-run reconciliation.
- The worker uses the same bootstrap; jobs/cron arrive in the scheduling feature.

## Tests

- `uv run pytest` — runs unit + stack-free tests.
- `PANTERA_INTEGRATION=1 uv run pytest` — also runs tests that require the live stack.

## Index Build — RAG Substrate (spec 6)

Once documents are ingested, build a searchable index for hybrid retrieval (dense + lexical).

### Trigger an index build

**Prerequisites**: At least one document must be ingested for the client (spec 4).

```bash
# Get a manager/admin token
TOKEN=$(curl -s -X POST http://localhost:8000/auth/jwt/login \
  -F "username=admin@pantera.io" -F "password=ChangeMe1!" | jq -r .access_token)

# Trigger the build (returns 202 Accepted, runs in the background)
curl -X POST http://localhost:8000/clients/<client_id>/index \
  -H "Authorization: Bearer $TOKEN"

# Monitor the build
curl http://localhost:8000/clients/<client_id>/index-runs \
  -H "Authorization: Bearer $TOKEN"
```

### Index build details

- **What it does**: Parses all documents for the client by source type → chunks them to ~256
  tokens → embeds via the modelserver → persists with dense + lexical vectors.
- **Who can trigger**: Manager or admin staff. Reviewer and client-user get 403.
- **Concurrency**: At most one build per client at a time; concurrent triggers join the
  in-flight run (202 response, no duplicates).
- **Idempotency**: Already-indexed documents are skipped. Re-running the same corpus yields
  0 new chunks.
- **Incremental**: Adding new documents causes only those docs to be processed on the next run.
- **Watchlist filtering**: Documents linked only to inactive watchlists are excluded.
- **Failure handling**: Permanent parse errors are logged and skipped. Transient failures
  (modelserver down, timeout) are retried on the next run.
- **Monitoring**: Check `GET /index-runs` for status; `GET /index-state` for per-document progress.

### Storage

Chunks are stored in the `chunks` table with:
- Dense 768-dim L2-normalized embedding (vectors, cosine search via HNSW index)
- Lexical tsvector (full-text search via GIN index)
- Metadata: chunk_type, section, source_reliability, date (from document), document_id, ordinal
- Per-document state: status, chunk_count, embedder_version, attempts, last_error (in
  `document_index_state`)

## Troubleshooting

- "Cannot reach Vault" → ensure the `vault` container is healthy and secrets were written.
- "Required secret(s) missing" → re-run `scripts/write_secrets.py` with the needed env vars.
- 429 on PubMed/openFDA → add the optional API keys to Vault (see Ingestion section above).
- Build fails with "Embedder version mismatch" → modelserver is running a different artifact.
  Ensure both the app and modelserver use the same embedder artifact (SHA-256 mismatch is
  detected at build start and fails fast).

## Modelserver (lean inference container, spec 5)

Operational notes for the modelserver — a lean, stateless inference container (FastAPI +
onnxruntime + numpy + no-torch tokenizers). Source layout: `modelserver/core/` (config, logging,
auth, manifest, startup), `modelserver/inference/` (classifier, embedder, tokenize),
`modelserver/eval/` (run_eval, bench), `modelserver/models/` (committed artifacts).

### Image size check (< 500 MB)

After building, verify the image stays under 500 MB (D1/Principle VI):

```bash
docker compose build modelserver
docker images pantera-modelserver --format "{{.Size}}"
```

If the image grows beyond 500 MB:
- Ensure the Dockerfile uses `uv sync --only-group modelserver --no-install-project` (not
  `--group`, which pulls in `[project].dependencies`).
- The `training` group (torch ~2 GB) must never appear in the serving image.
- The `modelserver` group is self-contained: fastapi, uvicorn, onnxruntime, numpy, tokenizers,
  pydantic, pydantic-settings, structlog, hvac, secure, scikit-learn, joblib, pyyaml.

### Git LFS for large artifacts

If any artifact in `modelserver/models/` exceeds 100 MB, track it with Git LFS:

```bash
git lfs track "modelserver/models/*.onnx"
git lfs track "modelserver/models/*.joblib"
git add .gitattributes modelserver/models/
```

Current artifacts (v1.0) are small (< 5 MB); Git LFS is only needed if a production BiomedBERT
ONNX model replaces the current placeholder.

### Rotating the modelserver_token

The service reads its token from Vault at startup (`pantera/secrets.modelserver_token`); rotation
needs no code change:

1. Write the new token to Vault (`hvac` create_or_update_secret on `pantera/secrets`).
2. `docker compose restart modelserver` to pick it up.
3. Update callers (api/worker) to the same new token in Vault and restart them. The token is
   checked per request via `hmac.compare_digest`; the new value takes effect on next restart.

### Updating model artifacts

```bash
uv run python scripts/generate_model_artifacts.py     # minimal dev artifacts
# OR run notebooks/01_train_export_modelserver.ipynb   # production BiomedBERT
uv run python modelserver/eval/run_eval.py            # must print PASS (macro-F1 >= 0.80)
docker compose build modelserver && docker compose up -d --wait modelserver
curl http://localhost:8001/ready                      # should show new sha256 values
```

Note: the api image also ships `modelserver/models/tokenizer.json` (the app counts tokens with the
embedder's tokenizer — FR-025), so regenerating the tokenizer means rebuilding **both** images.

## RAG Retrieval (spec 7)

### Search endpoint

```bash
# Search a client's evidence corpus (reviewer or manager staff)
TOKEN=$(curl -s -X POST http://localhost:8000/auth/jwt/login \
  -d "username=reviewer@example.com&password=..." | jq -r .access_token)

curl http://localhost:8000/clients/<client_id>/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "hepatotoxicity drug induced", "top_k": 10}'
```

Response includes: `results[]` (ranked passages with provenance), `corroboration_count`
(distinct documents), `corroboration_sources[]`, `query_hash` (PII-free), `embedder_version`.

**Error codes**:
- `409 EMBEDDER_VERSION_MISMATCH` — the client's chunk index was built with a different embedder;
  rebuild the index before querying.
- `502 MODELSERVER_UNAVAILABLE` — the modelserver is down or erroring; check `GET /health` on port 8001.
- `400 CLIENT_SUSPENDED` — client is suspended; reactivate before searching.

### Reranker artifact rebuild

When a new cross-encoder checkpoint is available:

```bash
# Run the export notebook (requires uv training group — torch + optimum)
uv run --group training jupyter notebook notebooks/02_train_export_reranker.ipynb

# Update manifest.json with the SHA-256 printed at the end of the notebook (T033)
# Then verify the modelserver boots and /ready shows the reranker
docker compose restart modelserver
curl http://localhost:8001/ready | jq .models.reranker

# Image size check (must stay < 500 MB)
docker images pantera-modelserver --format "{{.Size}}"
```

### RAG eval run

```bash
# Print thresholds and golden-set stats
uv run python eval/rag/run_rag_eval.py

# Run the full eval gate (requires PANTERA_INTEGRATION=1 + docker compose up)
PANTERA_INTEGRATION=1 uv run pytest tests/integration/test_rag_eval.py -v

# Expected output: hit_at_5 >= 0.85, mrr >= 0.70, corroboration_accuracy >= 1.0
```

### Query-embedding cache

Query embeddings are cached in Redis with a version-scoped key
`rag:qemb:{embedder_sha}:{query_hash}` and a configurable TTL (default 3600 s,
`Settings.query_embedding_cache_ttl`). Cache outages are non-fatal — the query proceeds
via a live embed call.

To clear all cached query embeddings after an embedder upgrade:
```bash
redis-cli -h localhost -p 6379 KEYS "rag:qemb:*" | xargs redis-cli DEL
```

### Latency monitoring

The modelserver's `/ready` endpoint includes a rolling-window latency breakdown:

## Triage & Routing (spec 8)

Triage fires automatically after each document is indexed. No manual trigger is needed.

### scispaCy model setup

The `en_ner_bc5cdr_md` model is declared as a project dependency and installed via `uv sync`.
If the package wheel URL is ever unavailable (S3 outage), install it manually:
```bash
pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_ner_bc5cdr_md-0.5.4.tar.gz
```
The model is loaded once per process (`@lru_cache`); it does not run in the modelserver container.

### Query a finding's triage state

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/jwt/login \
  -d "username=reviewer@example.com&password=..." | jq -r .access_token)

curl http://localhost:8000/clients/<client_id>/findings/<finding_id> \
  -H "Authorization: Bearer $TOKEN"
```

Response shape: `id`, `client_id`, `document_id`, `drug`, `reaction`, `bucket`, `status`,
`resolution_path`, `model_confidence`, `created_at`.

**Bucket → status mapping**:
- `emergency` / `urgent` → `pending_expedited` (review queue)
- `minor` / `positive` → `pending_batch` (batch queue)
- `irrelevant` → `classified` (no action)

**Error codes**:
- `404` — finding not found or belongs to a different client.
- `400 CLIENT_SUSPENDED` — client is suspended.

### LLM configuration

Triage uses the LLM configured in Vault (`anthropic_api_key` → Anthropic, else `openai_api_key` →
OpenAI). In CI, `anthropic_api_key=ci-test-key` is a sentinel that will fail real LLM calls; the
integration test mocks the LLM at the function level so no real provider is contacted.

### Triage eval gate

```bash
# Run the golden-set eval (self-contained, no docker stack required)
uv run pytest tests/integration/test_triage_eval.py -v
# Expected: recall >= 0.90, precision >= 0.75, FN <= FP (SC-003)
```

### Staleness sweep (operator alert)

Documents that are `INDEXED` but have zero findings after `triage_staleness_max_age_minutes`
(default 30 min) emit `triage.operator_alert` (stage=sweep). These appear in structured logs:
```
{"event": "triage.operator_alert", "stage": "sweep", "document_id": ..., "reason": "indexed_with_no_finding_past_staleness_window"}
```
Routing these to a paging system is spec 11.
```bash
curl http://localhost:8001/ready | jq .latency_ms
# Shows p50/p95 for classify, embed, rerank operations
```

For the end-to-end retrieval latency, check the structured logs for `rag.search.ok` events
which include `result_count`. Warm-cache median latency target is < 1 s for default top-K
of 10 (SC-006).
