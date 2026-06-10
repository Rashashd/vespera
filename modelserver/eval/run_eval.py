"""Eval gate: load shipped classifier, score macro-F1, exit non-zero if below threshold.

Usage (from repo root):
    uv run python modelserver/eval/run_eval.py

Env overrides:
    MODEL_DIR      — path to directory containing classifier.joblib (default: modelserver/models)
    EVAL_SET_PATH  — path to eval_set.jsonl (default: modelserver/eval/eval_set.jsonl)
    THRESHOLD_PATH — path to eval_thresholds.yaml (default: eval_thresholds.yaml)

Exit codes:
    0  PASS — macro-F1 >= threshold
    1  FAIL — macro-F1 < threshold or any error
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml


def _load_threshold(threshold_path: Path) -> float:
    data = yaml.safe_load(threshold_path.read_text())
    return float(data["classifier"]["min"])


def _load_eval_set(eval_path: Path) -> tuple[list[str], list[int]]:
    texts, labels = [], []
    for line in eval_path.read_text().splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        texts.append(obj["text"])
        labels.append(int(obj["label"]))
    return texts, labels


def _score_joblib(model_dir: Path, texts: list[str], labels: list[int]) -> float:
    import joblib
    from sklearn.metrics import f1_score

    clf = joblib.load(model_dir / "classifier.joblib")
    preds = clf.predict(texts)
    return float(f1_score(labels, preds, average="macro"))


def _score_onnx(model_dir: Path, texts: list[str], labels: list[int]) -> float:
    import numpy as np
    import onnxruntime as ort
    from sklearn.metrics import f1_score

    from modelserver.inference.tokenize import load_tokenizer, tokenize_batch

    tokenizer = load_tokenizer(str(model_dir / "tokenizer.json"))
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 1
    session = ort.InferenceSession(str(model_dir / "classifier.onnx"), sess_options=opts)
    input_ids, attention_mask = tokenize_batch(tokenizer, texts)
    outputs = session.run(None, {"input_ids": input_ids, "attention_mask": attention_mask})
    logits = outputs[0]
    exp = np.exp(logits - logits.max(axis=1, keepdims=True))
    probs = exp / exp.sum(axis=1, keepdims=True)
    preds = probs.argmax(axis=1)
    return float(f1_score(labels, preds, average="macro"))


def main() -> int:
    repo_root = Path(__file__).parent.parent.parent
    model_dir = Path(
        __import__("os").environ.get("MODEL_DIR", str(repo_root / "modelserver" / "models"))
    )
    eval_path = Path(
        __import__("os").environ.get(
            "EVAL_SET_PATH", str(repo_root / "modelserver" / "eval" / "eval_set.jsonl")
        )
    )
    threshold_path = Path(
        __import__("os").environ.get("THRESHOLD_PATH", str(repo_root / "eval_thresholds.yaml"))
    )

    threshold = _load_threshold(threshold_path)
    texts, labels = _load_eval_set(eval_path)

    if not texts:
        print("ERROR: eval_set.jsonl is empty", file=sys.stderr)
        return 1

    joblib_path = model_dir / "classifier.joblib"
    onnx_path = model_dir / "classifier.onnx"

    if joblib_path.exists():
        f1 = _score_joblib(model_dir, texts, labels)
    elif onnx_path.exists():
        f1 = _score_onnx(model_dir, texts, labels)
    else:
        print(
            f"ERROR: no classifier artifact found in {model_dir} "
            "(expected classifier.joblib or classifier.onnx)",
            file=sys.stderr,
        )
        return 1

    result = "PASS" if f1 >= threshold else "FAIL"
    print(f"macro_f1={f1:.4f}  threshold={threshold:.2f}  {result}")

    return 0 if f1 >= threshold else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
