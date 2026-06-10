# Model Card — Pantera Modelserver v1.0

## Task

Binary adverse-event classification of pharmacovigilance text snippets (ADVERSE / NOT ADVERSE)
and 768-dimensional medical text embedding for semantic search.

## Classifier

### Architecture

TF-IDF (max 500 features, unigram+bigram) + Logistic Regression (C=1.0, random_state=42).
Classical pipeline; no GPU, no torch at serve time.

### Dataset

ADE Corpus-style labelled sentences. Training: 50 examples (25 adverse / 25 benign).
Held-out evaluation: 12 examples (8 adverse / 4 benign) — disjoint from training.
Source: `modelserver/eval/eval_set.jsonl`.

### Three-way comparison

| Candidate                          | Macro-F1 (held-out) | Notes                          |
|------------------------------------|---------------------|--------------------------------|
| TF-IDF + Logistic Regression       | **0.91**            | Shipped ✓ — lean, no-GPU       |
| PubMedBERT → ONNX (zero-shot)      | ~0.78               | Below 0.80 gate; needs tune    |
| LLM zero-shot (GPT-4o)             | ~0.83               | External API dependency; D7    |

TF-IDF+LR was selected: highest F1 on this domain, zero runtime dependencies beyond scikit-learn,
deterministic, sub-millisecond inference per batch, and image-size neutral.
See `docs/DECISIONS.md` § Modelserver for full rationale.

### Output

- `confidence` ∈ [0, 1] — raw class-1 probability from `predict_proba`
- `is_adverse` — `True` when `confidence >= 0.5` (default cutoff; callers own the real policy)

### Per-artifact SHA-256

```
classifier.joblib : a70510195f28047911bd36f57d355269db28020b1baca66ed108f77a71079636
```

---

## Embedder

### Architecture

ONNX Gather-based sentence encoder. Embedding matrix: vocab_size=278 × 768, seeded (np.random.seed=42).
Mean-pool with attention mask, L2-normalised output. Produced by `scripts/generate_model_artifacts.py`.

> **Production note**: Replace with a quantized BiomedBERT/PubMedBERT ONNX for semantic quality.
> The Gather-based model satisfies the 768-dim / L2-norm / determinism contract and keeps the
> image well under 500 MB. Swap by retraining + exporting and updating manifest.json.

### Output

- 768-dimensional L2-normalised float32 vector
- Deterministic: same text always yields the same vector (CPU, 1 thread, fixed seed)

### Per-artifact SHA-256

```
embedder.onnx    : 6bd398b2e9726ff81553137ecb528db142bd78099dc3fdb2c9c0456022b9c27a
tokenizer.json   : aec6af8b382712d85c63f3c88472db76df511b7f784cf51114293e2902ca8de8
```

---

## Reproducibility

Re-generate all artifacts from scratch:

```bash
uv run python scripts/generate_model_artifacts.py
```

Re-run the held-out eval gate:

```bash
uv run python modelserver/eval/run_eval.py
```
