"""Unit tests for the eval gate (US5 / T037).

Verifies that run_eval.py passes at/above threshold and exits non-zero below.
Uses a tiny in-process classifier fixture — no real models needed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import joblib
import pytest
import yaml
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline


# Skip tests that load the real 110 MB ONNX when LFS hasn't been downloaded.
# (LFS pointer files are ~133 bytes; real model is >100 MB.)
def _real_onnx_present() -> bool:
    p = Path(__file__).parent.parent.parent / "modelserver" / "models" / "classifier.onnx"
    try:
        return p.stat().st_size > 1_000_000
    except OSError:
        return False


_skip_no_onnx = pytest.mark.skipif(
    not _real_onnx_present(),
    reason="Real ONNX artifacts not present (lfs not downloaded)",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_always_correct_clf(dest: Path) -> None:
    """A classifier that always predicts the majority class (1 = adverse)."""
    from sklearn.feature_extraction.text import TfidfVectorizer

    X = [
        "patient developed severe liver failure",
        "drug caused acute kidney injury",
        "no adverse events reported",
        "well tolerated by participants",
    ]
    y = [1, 1, 0, 0]
    clf = Pipeline(
        [
            ("tfidf", TfidfVectorizer(max_features=50)),
            ("lr", LogisticRegression(random_state=42, max_iter=200)),
        ]
    )
    clf.fit(X, y)
    joblib.dump(clf, dest)


def _write_eval_set(dest: Path, data: list[dict]) -> None:
    dest.write_text("\n".join(json.dumps(d) for d in data) + "\n")


def _write_threshold(dest: Path, min_f1: float) -> None:
    dest.write_text(yaml.dump({"classifier": {"metric": "macro_f1", "min": min_f1}}))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_eval_passes_at_threshold(tmp_path):
    """A perfect classifier should pass with threshold 0.80."""
    clf_path = tmp_path / "classifier.joblib"
    _make_always_correct_clf(clf_path)

    eval_data = [
        {"text": "patient developed severe liver failure after drug", "label": 1},
        {"text": "drug caused acute kidney injury in elderly patients", "label": 1},
        {"text": "no adverse events reported in the clinical trial", "label": 0},
        {"text": "well tolerated by all study participants", "label": 0},
    ]
    eval_path = tmp_path / "eval_set.jsonl"
    _write_eval_set(eval_path, eval_data)

    threshold_path = tmp_path / "thresholds.yaml"
    _write_threshold(threshold_path, 0.80)

    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).parent.parent.parent / "modelserver" / "eval" / "run_eval.py"),
        ],
        capture_output=True,
        text=True,
        env={
            **__import__("os").environ,
            "MODEL_DIR": str(tmp_path),
            "EVAL_SET_PATH": str(eval_path),
            "THRESHOLD_PATH": str(threshold_path),
        },
    )
    assert result.returncode == 0, f"Expected PASS:\n{result.stdout}\n{result.stderr}"
    assert "PASS" in result.stdout


def test_eval_fails_below_threshold(tmp_path):
    """run_eval exits non-zero when threshold exceeds maximum possible F1."""
    clf_path = tmp_path / "classifier.joblib"
    _make_always_correct_clf(clf_path)

    eval_data = [
        {"text": "patient developed severe liver failure after drug", "label": 1},
        {"text": "no adverse events reported in the clinical trial", "label": 0},
    ]
    eval_path = tmp_path / "eval_set.jsonl"
    _write_eval_set(eval_path, eval_data)

    threshold_path = tmp_path / "thresholds.yaml"
    # Threshold > 1.0 is unreachable — forces FAIL regardless of classifier score
    _write_threshold(threshold_path, 1.1)

    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).parent.parent.parent / "modelserver" / "eval" / "run_eval.py"),
        ],
        capture_output=True,
        text=True,
        env={
            **__import__("os").environ,
            "MODEL_DIR": str(tmp_path),
            "EVAL_SET_PATH": str(eval_path),
            "THRESHOLD_PATH": str(threshold_path),
        },
    )
    assert result.returncode == 1, f"Expected FAIL:\n{result.stdout}\n{result.stderr}"
    assert "FAIL" in result.stdout


def test_eval_missing_classifier_exits_1(tmp_path):
    eval_path = tmp_path / "eval_set.jsonl"
    _write_eval_set(eval_path, [{"text": "test", "label": 0}])
    threshold_path = tmp_path / "thresholds.yaml"
    _write_threshold(threshold_path, 0.80)

    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).parent.parent.parent / "modelserver" / "eval" / "run_eval.py"),
        ],
        capture_output=True,
        text=True,
        env={
            **__import__("os").environ,
            "MODEL_DIR": str(tmp_path),
            "EVAL_SET_PATH": str(eval_path),
            "THRESHOLD_PATH": str(threshold_path),
        },
    )
    assert result.returncode == 1


@_skip_no_onnx
@pytest.mark.skipif(os.getenv("CI") != "true", reason="OOM on low-RAM machines; CI-only")
def test_eval_with_real_shipped_artifacts():
    """The real shipped classifier must pass the real eval gate."""
    repo_root = str(Path(__file__).parent.parent.parent)
    result = subprocess.run(
        [sys.executable, "modelserver/eval/run_eval.py"],
        capture_output=True,
        text=True,
        cwd=repo_root,
        env={**os.environ, "PYTHONPATH": repo_root},
    )
    assert (
        result.returncode == 0
    ), f"Shipped classifier failed eval gate:\n{result.stdout}\n{result.stderr}"
    assert "PASS" in result.stdout


@_skip_no_onnx
@pytest.mark.skipif(os.getenv("CI") != "true", reason="OOM on low-RAM machines; CI-only")
def test_eval_main_in_process_pass(tmp_path):
    """Call main() in-process for coverage (uses shipped artifacts)."""
    from modelserver.eval.run_eval import main

    repo_root = Path(__file__).parent.parent.parent
    _prev_model_dir = os.environ.get("MODEL_DIR")
    os.environ["MODEL_DIR"] = str(repo_root / "modelserver" / "models")
    os.environ["EVAL_SET_PATH"] = str(repo_root / "modelserver" / "eval" / "eval_set.jsonl")
    os.environ["THRESHOLD_PATH"] = str(repo_root / "eval_thresholds.yaml")
    try:
        rc = main()
    finally:
        if _prev_model_dir is not None:
            os.environ["MODEL_DIR"] = _prev_model_dir
        else:
            os.environ.pop("MODEL_DIR", None)
        os.environ.pop("EVAL_SET_PATH", None)
        os.environ.pop("THRESHOLD_PATH", None)
    assert rc == 0


def test_eval_main_in_process_fail(tmp_path):
    """main() returns 1 when threshold exceeds maximum possible F1."""
    from modelserver.eval.run_eval import main

    clf_path = tmp_path / "classifier.joblib"
    _make_always_correct_clf(clf_path)
    eval_data = [
        {"text": "patient developed severe liver failure after drug", "label": 1},
        {"text": "no adverse events reported in the clinical trial", "label": 0},
    ]
    eval_path = tmp_path / "eval_set.jsonl"
    _write_eval_set(eval_path, eval_data)
    threshold_path = tmp_path / "thresholds.yaml"
    # Threshold > 1.0 is unreachable — forces FAIL regardless of classifier score
    _write_threshold(threshold_path, 1.1)

    _prev_model_dir = os.environ.get("MODEL_DIR")
    os.environ["MODEL_DIR"] = str(tmp_path)
    os.environ["EVAL_SET_PATH"] = str(eval_path)
    os.environ["THRESHOLD_PATH"] = str(threshold_path)
    try:
        rc = main()
    finally:
        if _prev_model_dir is not None:
            os.environ["MODEL_DIR"] = _prev_model_dir
        else:
            os.environ.pop("MODEL_DIR", None)
        os.environ.pop("EVAL_SET_PATH", None)
        os.environ.pop("THRESHOLD_PATH", None)
    assert rc == 1


def test_eval_main_missing_classifier(tmp_path):
    """main() returns 1 when no classifier artifact exists."""
    from modelserver.eval.run_eval import main

    eval_data = [{"text": "test", "label": 0}]
    eval_path = tmp_path / "eval_set.jsonl"
    _write_eval_set(eval_path, eval_data)
    threshold_path = tmp_path / "thresholds.yaml"
    _write_threshold(threshold_path, 0.80)

    _prev_model_dir = os.environ.get("MODEL_DIR")
    os.environ["MODEL_DIR"] = str(tmp_path)
    os.environ["EVAL_SET_PATH"] = str(eval_path)
    os.environ["THRESHOLD_PATH"] = str(threshold_path)
    try:
        rc = main()
    finally:
        if _prev_model_dir is not None:
            os.environ["MODEL_DIR"] = _prev_model_dir
        else:
            os.environ.pop("MODEL_DIR", None)
        os.environ.pop("EVAL_SET_PATH", None)
        os.environ.pop("THRESHOLD_PATH", None)
    assert rc == 1
