"""Triage golden-set eval gate: recall>=0.90, precision>=0.75, FN<=FP (SC-003).

Reads tests/data/triage_golden_set.jsonl and eval_thresholds.yaml.
Self-contained — mocks modelserver and LLM; no database or PANTERA_INTEGRATION required.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from app.triage.classify import resolve_adverse
from app.triage.enums import Bucket
from app.triage.severity import assign_bucket

_GOLDEN_SET = Path(__file__).resolve().parent.parent / "data" / "triage_golden_set.jsonl"
_THRESHOLDS = Path(__file__).resolve().parent.parent.parent / "eval_thresholds.yaml"

_EXPEDITED_BUCKETS = {Bucket.URGENT, Bucket.EMERGENCY}


def _load_golden_set() -> list[dict]:
    cases = []
    with _GOLDEN_SET.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def _load_thresholds() -> dict:
    with _THRESHOLDS.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


async def _evaluate_case(case: dict) -> str:
    """Run the triage classification logic for one golden-set case.

    Mocks the modelserver and LLM; applies the real three-stage decision and severity bucketing.
    Returns the actual bucket name.
    """
    conf = case["model_confidence"]
    is_adverse = case["model_is_adverse"]
    source_reliability = case["source_reliability"]
    custom_keywords = case.get("custom_keywords", [])
    text = case["text"]
    llm_resolve_raises = case.get("llm_resolve_raises", False)

    ms_client = AsyncMock()
    ms_client.classify.return_value = [{"confidence": conf, "is_adverse": is_adverse}]

    settings = MagicMock()
    settings.triage_confidence_threshold = 0.70

    llm_resolve_adverse = case.get("llm_resolve_adverse")
    llm_valence = case.get("llm_valence")

    async def _llm_resolve(t, r):
        if llm_resolve_raises:
            raise RuntimeError("LLM unavailable")
        return bool(llm_resolve_adverse)

    verdict, model_confidence, _path = await resolve_adverse(
        text=text,
        ms_client=ms_client,
        settings=settings,
        llm_resolve_fn=_llm_resolve,
        source_reliability=source_reliability,
        client_id=0,
        document_id=0,
    )

    if verdict:
        bucket = assign_bucket(
            verdict=True,
            text=text,
            source_reliability=source_reliability,
            custom_keywords=custom_keywords,
        )
    else:
        # Simulate assess_valence result from golden set (no real LLM call)
        valence = llm_valence if llm_valence else "irrelevant"
        bucket = Bucket.POSITIVE if valence == "positive" else Bucket.IRRELEVANT

    return bucket.value


@pytest.mark.asyncio
async def test_triage_golden_set_eval():
    """Eval gate: recall>=0.90, precision>=0.75, FN<=FP (SC-003 escalation bias)."""
    thresholds = _load_thresholds()
    recall_min = thresholds["triage"]["recall_min"]
    precision_min = thresholds["triage"]["precision_min"]

    cases = _load_golden_set()
    assert cases, "Golden set is empty"

    tp = fp = fn = tn = 0
    failures: list[str] = []

    for case in cases:
        actual_bucket_name = await _evaluate_case(case)
        actual_bucket = Bucket(actual_bucket_name)
        expected_bucket = Bucket(case["expected_bucket"])
        expected_expedited = case["expected_expedited"]
        actual_expedited = actual_bucket in _EXPEDITED_BUCKETS

        if expected_expedited and actual_expedited:
            tp += 1
        elif not expected_expedited and actual_expedited:
            fp += 1
            failures.append(
                f"FP {case['id']}: expected={expected_bucket.value} actual={actual_bucket.value}"
            )
        elif expected_expedited and not actual_expedited:
            fn += 1
            failures.append(
                f"FN {case['id']}: expected={expected_bucket.value} actual={actual_bucket.value}"
            )
        else:
            tn += 1

    total_positives = tp + fn
    total_predicted_positive = tp + fp

    recall = tp / total_positives if total_positives > 0 else 1.0
    precision = tp / total_predicted_positive if total_predicted_positive > 0 else 1.0

    failure_summary = "\n".join(failures) if failures else "none"
    assert (
        recall >= recall_min
    ), f"Recall {recall:.3f} < {recall_min} — misclassified cases:\n{failure_summary}"
    assert (
        precision >= precision_min
    ), f"Precision {precision:.3f} < {precision_min} — misclassified cases:\n{failure_summary}"
    # SC-003: prefer false positives over false negatives (escalation bias)
    assert (
        fn <= fp
    ), f"SC-003 violated: FN={fn} > FP={fp} (system is under-escalating)\n{failure_summary}"
