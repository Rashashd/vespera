"""Medical text embedder: tokenize → ONNX → mean-pool → L2-normalize → 768-dim.

Deterministic: CPU provider, fixed threads (D3/D6/FR-002/FR-004).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


class EmbedderSession:
    """Wraps an ONNX sentence encoder; embed(texts) → L2-normalized 768-dim vectors."""

    def __init__(self, model_path: Path, tokenizer, max_tokens: int = 512) -> None:
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self._session = ort.InferenceSession(
            str(model_path),
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )
        self._tokenizer = tokenizer
        self._max_tokens = max_tokens

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return L2-normalized 768-dim vectors for each text; empty → []."""
        if not texts:
            return []

        from modelserver.inference.tokenize import tokenize_batch

        input_ids, attention_mask = tokenize_batch(
            self._tokenizer, texts, max_length=self._max_tokens
        )
        need = {i.name for i in self._session.get_inputs()}
        feed: dict = {"input_ids": input_ids, "attention_mask": attention_mask}
        if "token_type_ids" in need:
            feed["token_type_ids"] = np.zeros_like(input_ids)
        outputs = self._session.run(None, {k: v for k, v in feed.items() if k in need})
        # last_hidden_state: [B, S, 768]
        last_hidden_state = outputs[0].astype(np.float32)

        # Attention-mask-weighted mean pool: [B, S, 1]
        mask = attention_mask[:, :, np.newaxis].astype(np.float32)
        sum_hidden = np.sum(last_hidden_state * mask, axis=1)  # [B, 768]
        sum_mask = np.maximum(np.sum(mask, axis=1), 1e-9)  # [B, 1]
        mean_pooled = sum_hidden / sum_mask  # [B, 768]

        # L2 normalise
        norms = np.maximum(np.linalg.norm(mean_pooled, axis=1, keepdims=True), 1e-9)
        return (mean_pooled / norms).tolist()
