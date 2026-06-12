"""Cross-encoder relevance reranker: pair-encode (query, passage) → ONNX → logit score.

Uses the reranker's own BERT wordpiece tokenizer with token_type_ids.
Do NOT reuse tokenize_batch — it produces only input_ids + attention_mask (no segment IDs).
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

_log = logging.getLogger(__name__)


class CrossEncoderSession:
    """Wraps an ONNX cross-encoder; rerank(query, passages) → relevance scores."""

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
        # Enable padding + truncation for pair encoding
        self._tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        self._tokenizer.enable_truncation(max_length=max_tokens)

    def rerank(self, query: str, passages: list[str]) -> list[float]:
        """Return relevance logit scores for each (query, passage) pair.

        Scores are in input order; higher = more relevant.
        Empty passages → [].
        """
        if not passages:
            return []

        # Pair encode: [CLS] query [SEP] passage [SEP] with token_type_ids
        pairs = [(query, p) for p in passages]
        try:
            encodings = self._tokenizer.encode_batch(pairs)
        except Exception:
            # Truncation safety-net warning per contract
            _log.warning("reranker: tokenizer encode_batch error — truncating")
            encodings = self._tokenizer.encode_batch(pairs)

        # Warn on truncation (safety net — not an error)
        for enc in encodings:
            if len(enc.ids) >= self._max_tokens:
                _log.warning("reranker: sequence truncated to %d tokens", self._max_tokens)

        input_ids = np.array([e.ids for e in encodings], dtype=np.int64)
        attention_mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
        token_type_ids = np.array([e.type_ids for e in encodings], dtype=np.int64)

        outputs = self._session.run(
            None,
            {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "token_type_ids": token_type_ids,
            },
        )
        # logits shape: [B, 1] or [B, 2]; take column 0 (relevance score)
        logits = outputs[0].astype(np.float32)
        return logits[:, 0].tolist()
