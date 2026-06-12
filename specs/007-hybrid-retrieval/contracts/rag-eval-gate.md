# Contract: RAG eval gate (first RAG gate — Principle IV)

The committed retrieval quality gate. Encoded as an integration test (real DB + embedder + reranker)
plus a manual CLI, with thresholds in `eval_thresholds.yaml`.

## `eval_thresholds.yaml` (addition)

```yaml
classifier:
  metric: macro_f1
  min: 0.80
rag:
  hit_at_5: 0.85
  mrr: 0.70
  corroboration_accuracy: 1.0
```

## Golden set — `eval/rag/golden_set.jsonl` (~15 lines)

```jsonc
{ "query": "hepatotoxicity from DrugX", "relevant_document_keys": ["PMID:111", "PMID:222"],
  "expected_corroboration_count": 2 }
{ "query": "QT prolongation DrugY", "relevant_document_keys": ["PMID:333"],
  "expected_corroboration_count": null }   // null = not a corroboration case
```

`relevant_document_keys` are `documents.normalized_external_id`s; the eval seeds those documents (with
realistic chunk text) for a throwaway client so the corpus is reproducible.

## Metrics (computed by `eval/rag/run_rag_eval.py`, shared with the test)

- **hit@5**: fraction of cases where ≥ 1 `relevant_document_key` appears among the top-5 **distinct
  documents** in `results`.
- **MRR**: mean over cases of `1 / rank_of_first_relevant_document` (0 if none retrieved).
- **corroboration_accuracy**: over cases with non-null `expected_corroboration_count`, fraction where
  `response.corroboration_count == expected`.

## Gate — `tests/integration/test_rag_eval.py`

1. Seed the golden documents for a fresh client; build chunk embeddings + rerank via the **in-process
   modelserver ASGI app** (`httpx.ASGITransport`, `MODEL_DIR=modelserver/models`; skip if `onnxruntime`
   absent) — the real embed + rerank path, no separate modelserver container.
2. Run the full retrieval pipeline per golden query.
3. Compute the three metrics; **assert** `hit_at_5 ≥`, `mrr ≥`, `corroboration_accuracy ≥` the
   `eval_thresholds.yaml[rag]` values → **fail CI on regression**.
4. **Improvement proof (FR-026)**: also compute dense-only hit@5/MRR and assert hybrid+rerank
   `≥` dense-only on both (the "justified improvement", Brief §5-D / Principle IV).

## CI wiring

- Runs in the **integration test job** (Postgres+pgvector service + `uv sync --group modelserver` so
  `onnxruntime` + `modelserver/models` are present for the in-process modelserver app), not the lean
  classifier `eval` job (no DB there). No separate modelserver container required.
- Faithfulness / answer-relevancy are **out of scope** here (no LLM answer generation) — deferred to the
  grounded-report/agent spec; recorded as a known boundary.
</content>
