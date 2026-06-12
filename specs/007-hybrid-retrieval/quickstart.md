# Quickstart: Hybrid RAG Retrieval & Multi-Source Corroboration

Validation/run guide for Spec 7. Implementation detail lives in `tasks.md`; design in `plan.md`,
`research.md`, `data-model.md`, and `contracts/`.

## Prerequisites

- Spec 6 merged (the `chunks` index exists; a client with indexed chunks). The Postgres image is
  already `pgvector/pgvector:pg16`.
- The **modelserver rebuilt** with the new `reranker.onnx` + `reranker_tokenizer.json` (boot validates
  their SHA-256 — it will refuse to start if the manifest doesn't match).
- Secrets in Vault as usual (`modelserver_token` already loaded by the api; no new secret).
- On this Windows host, integration runs need `docker-compose.override.yml` (5433/6380) + the Vault
  repoint — see `memory/host-integration-test-vault-repoint.md`.

## Build & boot

```bash
# rebuild modelserver with the reranker artifact, then bring the stack up
docker compose build modelserver
docker compose up -d            # api + modelserver + postgres(pgvector) + redis + vault

# confirm the reranker is loaded and validated
curl -s localhost:8001/ready | jq '.models'   # expect classifier, embedder, tokenizer, reranker
```

## End-to-end validation (live stack)

1. **Index a client** (Spec 6) so there are chunks: `POST /clients/{id}/index`, wait for the run to
   reach `success`.
2. **Search**:
   ```bash
   curl -s -X POST localhost:8000/clients/{id}/search \
     -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" \
     -d '{"query":"hepatotoxicity associated with DrugX","top_k":10}' | jq
   ```
   Expect: ranked `results` (each with `text`, `score`, `rank`, provenance, anchor), plus
   `corroboration_count` and `corroboration_sources` listing **all** distinct source documents.
3. **Hybrid check**: a query using an exact rare term that is semantically diffuse still surfaces its
   passage (lexical leg); a paraphrase with no shared keywords still surfaces its passage (dense leg).
4. **Corroboration**: query an event reported by N seeded documents → `corroboration_count == N` and
   `len(corroboration_sources) == N`.
5. **Isolation**: the same query for a different client never returns the first client's chunks.
6. **Cache**: re-run the same query → served from the Redis cache (no second `/embed`; check
   modelserver `/ready` `embed.count` does not increase). Stop Redis → query still succeeds (live embed).
7. **Version safety**: with chunks indexed under embedder vX, point the modelserver at a different
   embedder version → the search returns **409 `EMBEDDER_VERSION_MISMATCH`** (rebuild required), never
   wrong results.
8. **Empty corpus**: a brand-new client with no chunks → `200` with `results: []`,
   `corroboration_count: 0`.

## Tests

```bash
# unit
uv run pytest tests/unit/test_rrf_fusion.py tests/unit/test_query_cache_key.py \
  tests/unit/test_corroboration.py tests/unit/test_version_mismatch.py

# integration (live stack)
PANTERA_INTEGRATION=1 uv run pytest tests/integration/test_retrieval_*.py \
  tests/integration/test_modelserver_rerank.py

# the RAG eval GATE (seeds golden corpus, scores, asserts thresholds)
PANTERA_INTEGRATION=1 uv run pytest tests/integration/test_rag_eval.py -q
# manual scorer (parity with the classifier gate)
uv run python eval/rag/run_rag_eval.py
```

## Lint & coverage (must pass before PR)

```bash
uv run ruff check app modelserver tests
uv run black --check app modelserver tests
uv run pytest --cov=app --cov=modelserver   # ≥ 80% overall
```

## Done = green

- All retrieval integration tests pass; isolation test shows zero foreign-client rows.
- `test_rag_eval.py` meets `eval_thresholds.yaml[rag]` (hit@5 ≥ 0.85, MRR ≥ 0.70, corroboration = 100%)
  **and** hybrid+rerank ≥ dense-only.
- `/ready` lists the reranker; modelserver image stays < 500 MB.
- ruff + black clean; CI green (test job runs the RAG gate; lean `eval` job unchanged).
</content>
