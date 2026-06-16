"""Adverse-event classifier: onnxruntime (ONNX) or joblib (classical sklearn).

predict(texts) → [(confidence ∈ [0,1], is_adverse = confidence >= 0.5)]
Deterministic: CPU provider, fixed threads, no sampling (D6/FR-004).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


class ClassifierSession:
    """Wraps an ONNX or joblib classifier for deterministic adverse-event detection."""

    def __init__(
        self,
        model_path: Path,
        tokenizer=None,
        max_tokens: int = 512,
    ) -> None:
        self._format = model_path.suffix.lower()
        self._max_tokens = max_tokens
        self._tokenizer = tokenizer

        if self._format == ".onnx":  # pragma: no cover
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
        elif self._format == ".joblib":
            import joblib

            self._pipeline = joblib.load(model_path)
        else:
            raise ValueError(f"Unsupported classifier format: {self._format!r}")

    def predict(self, texts: list[str]) -> list[tuple[float, bool]]:
        """Return (confidence, is_adverse) per text in input order; empty → []."""
        if not texts:
            return []
        if self._format == ".joblib":
            return self._predict_joblib(texts)
        return self._predict_onnx(texts)

    def _predict_joblib(self, texts: list[str]) -> list[tuple[float, bool]]:
        probs = self._pipeline.predict_proba(texts)  # [N, 2]
        return [(float(row[1]), float(row[1]) >= 0.5) for row in probs]

    def _predict_onnx(self, texts: list[str]) -> list[tuple[float, bool]]:  # pragma: no cover
        from modelserver.inference.tokenize import tokenize_batch

        input_ids, attention_mask = tokenize_batch(
            self._tokenizer, texts, max_length=self._max_tokens
        )
        feed = {"input_ids": input_ids, "attention_mask": attention_mask}
        # BERT-family exports (e.g. BiomedBERT) declare a third input, token_type_ids; for
        # single-sequence classification it is all zeros. Supply it only when the model expects
        # it so non-BERT exports keep working.
        expected_inputs = {i.name for i in self._session.get_inputs()}
        if "token_type_ids" in expected_inputs:
            feed["token_type_ids"] = np.zeros_like(input_ids)
        outputs = self._session.run(None, feed)
        # Expect logits [N, 2] — apply softmax for class-1 probability
        logits = outputs[0].astype(np.float64)
        shifted = logits - logits.max(axis=1, keepdims=True)
        exp_l = np.exp(shifted)
        probs = exp_l / exp_l.sum(axis=1, keepdims=True)
        return [(float(row[1]), float(row[1]) >= 0.5) for row in probs]
