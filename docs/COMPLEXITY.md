# Algorithmic Complexity

## Classifier

Input: batch of **B** texts, each tokenized to at most **n = 512** tokens.
Model constants: **L** transformer layers, **d** hidden dimension.

| Step | Big-O |
|---|---|
| Tokenization (per text) | O(n) |
| Transformer attention (per layer, per text) | O(n² · d) |
| Full ONNX forward pass (per text) | O(L · n² · d) |
| Batch of B texts | **O(B · L · n² · d)** |

Because n ≤ 512 and L, d are fixed model constants, this simplifies to **O(B)** — linear in batch size, with a large constant per text.

---

## Retrieval

### Query time

**N** = total indexed chunks in pgvector/GIN.
**k** = candidate set size after index lookups.
**top\_k** = rerank window (small, fixed; e.g. 50).

| Step | Big-O |
|---|---|
| Dense lookup — HNSW (pgvector) | O(log N) |
| Lexical lookup — GIN tsvector | O(log N + k) |
| RRF fusion | O(k log k) |
| Cross-encoder rerank (top\_k bounded) | O(top\_k · L · n²) = **O(1)** |
| **Overall** | **O(log N)** |

The rerank step is constant because `top_k` is a small fixed number: the quadratic-attention cross-encoder only ever sees a tiny bounded candidate set, so query latency scales as O(log N) as the corpus grows.

### Index build (offline)

| Step | Big-O |
|---|---|
| Embed all chunks | O(N) |
| HNSW construction | O(N · log N · M) — M = connections per node |
| GIN tsvector build | O(N · w) — w = avg terms per document |
