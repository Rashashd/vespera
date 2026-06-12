# Contract: `POST /rerank` (modelserver)

New endpoint on the **existing** modelserver (no new container). Reranks `(query, passage)` pairs with
a cross-encoder served via `onnxruntime` (no torch). Mirrors `/classify` and `/embed`.

## Auth & readiness

- `Depends(require_service_token)` — requires the existing `X-Service-Token` (= `modelserver_token`).
- Refuses with `503` until `app.state.ready` (all artifacts SHA-256-validated at boot, including the
  new `reranker` + `reranker_tokenizer`).

## Request — `RerankRequest`

```jsonc
{ "query": "hepatotoxicity associated with DrugX",
  "passages": ["…passage 1…", "…passage 2…"] }   // 1..128 passages
```

## Response — `RerankResponse`

```jsonc
{
  "model_version": { "name": "reranker", "version": "v1.0-ms-marco-minilm-l6-int8", "sha256": "…" },
  "results": [
    { "score": 7.42, "model_version": { "name": "reranker", … } },   // input order
    { "score": -1.10, "model_version": { … } }
  ]
}
```

- `score` = the cross-encoder relevance logit; **higher = more relevant**. The server does NOT sort —
  results are returned in **input order**; the caller owns ordering/top-K (mirrors `/classify` raw
  confidence). Sigmoid is optional and does not change ordering.
- One `model_version` per result + one top-level, stamped from `Manifest.model_version("reranker")`.

## Behavior

- Batch ≤ 128 (`Field(max_length=128)`); larger batches are the caller's responsibility to chunk.
- Each `(query, passage)` tokenized with the **reranker** wordpiece tokenizer, truncated to 512 tokens
  (truncation logged as a warning, not an error — a safety net).
- Deterministic: CPU provider, `intra_op_num_threads=1` (matches embedder/classifier).
- Latency recorded in the `/ready` rolling window under key `rerank`.

## Inference module — `modelserver/inference/reranker.py`

`CrossEncoderSession(model_path, tokenizer, max_tokens=512)` with
`rerank(query: str, passages: list[str]) -> list[float]`. Empty passages → `[]`.

**⚠️ Do NOT reuse `modelserver/inference/tokenize.py::tokenize_batch`** — it produces only `input_ids`
and `attention_mask` (single-segment, for the embedder/classifier). A cross-encoder needs **pair
encoding with `token_type_ids`**. Implement pair tokenization here:

- `enc = tokenizer.encode_batch([(query, p) for p in passages])` (the reranker's own wordpiece
  tokenizer.json carries the BERT post-processor that inserts `[CLS] query [SEP] passage [SEP]` and the
  segment ids).
- Build three int64 arrays from each `Encoding`: `input_ids = e.ids`, `attention_mask =
  e.attention_mask`, `token_type_ids = e.type_ids`. Enable truncation (`max_length=512`) + padding on the
  tokenizer first (same pattern as `tokenize_batch`).
- ONNX run: `session.run(None, {"input_ids":…, "attention_mask":…, "token_type_ids":…})` — the
  `ms-marco-MiniLM` cross-encoder ONNX has **three** inputs (verify exact input names from the exported
  graph in the notebook and match them). Output logits are shape `[B, 1]`; the **score is `logits[:, 0]`**
  (higher = more relevant). No softmax/sigmoid needed (ordering only).
- Determinism: `ort.SessionOptions()` with `intra_op_num_threads = 1`, `CPUExecutionProvider` (match
  `EmbedderSession`).

## Startup / artifact validation

- `modelserver/main.py` loads `CrossEncoderSession` + reranker tokenizer into `app.state.reranker`.
- `modelserver/models/manifest.json` gains `reranker` + `reranker_tokenizer` entries; the existing
  `validate_artifacts()` iterates ALL artifacts → SHA-256 mismatch/missing **refuses boot** (FR-010/
  Principle: startup validation). No code change to the validator — adding manifest entries is enough.
- `reranker.onnx` committed under `modelserver/models/` (Git LFS if > 100 MB; quantized to keep the
  image < 500 MB — Principle VI).
</content>
