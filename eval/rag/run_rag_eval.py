"""RAG eval scorer: compute hit@5, MRR, corroboration_accuracy vs thresholds.

Functions are shared between the manual CLI and the integration test gate (test_rag_eval.py).
Standalone CLI prints thresholds and golden-set stats (no DB required).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def load_golden_set(path: Path) -> list[dict]:
    """Load JSONL golden set; skip blank lines."""
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def compute_metrics(
    golden: list[dict],
    results: list[dict],
) -> dict[str, float]:
    """Compute hit@5, MRR, corroboration_accuracy from pipeline results.

    Args:
        golden: golden cases with relevant_document_keys + expected_corroboration_count
        results: list of RetrieveResponse dicts in same order as golden

    Returns:
        dict with hit_at_5, mrr, corroboration_accuracy
    """
    if len(golden) != len(results):
        raise ValueError(
            f"Length mismatch: golden={len(golden)} results={len(results)}"
        )  # noqa: TRY003

    hits, mrr_scores, corr_checks = [], [], []

    for case, resp in zip(golden, results, strict=True):
        relevant = set(case["relevant_document_keys"])
        passages = resp.get("results", [])

        # Deduplicate by external_id in result order
        seen: list[str] = []
        seen_set: set[str] = set()
        for p in passages:
            ext = p.get("external_id") or ""
            if ext and ext not in seen_set:
                seen_set.add(ext)
                seen.append(ext)

        top5 = set(seen[:5])
        hits.append(1 if top5 & relevant else 0)

        mrr = 0.0
        for rank, d in enumerate(seen, 1):
            if d in relevant:
                mrr = 1.0 / rank
                break
        mrr_scores.append(mrr)

        expected = case.get("expected_corroboration_count")
        if expected is not None:
            # Count how many of the relevant docs actually appear in the results
            result_ext_ids = {p.get("external_id") for p in passages if p.get("external_id")}
            found = sum(1 for k in relevant if k in result_ext_ids)
            corr_checks.append(1 if found >= expected else 0)

    return {
        "hit_at_5": sum(hits) / len(hits),
        "mrr": sum(mrr_scores) / len(mrr_scores),
        "corroboration_accuracy": sum(corr_checks) / len(corr_checks) if corr_checks else 1.0,
    }


def check_thresholds(metrics: dict[str, float], thresholds: dict) -> list[str]:
    """Return failure messages for metrics below threshold (empty list = pass)."""
    failures = []
    for metric, min_val in thresholds.get("rag", {}).items():
        actual = metrics.get(metric, 0.0)
        if actual < min_val:
            failures.append(f"{metric}={actual:.4f} < threshold={min_val}")
    return failures


def main() -> None:
    try:
        import yaml
    except ImportError:
        print("pyyaml not available; install with: pip install pyyaml")
        sys.exit(1)

    here = Path(__file__).parent
    golden_path = here / "golden_set.jsonl"
    thresholds_path = here.parent.parent / "eval_thresholds.yaml"

    golden = load_golden_set(golden_path)
    thresholds = yaml.safe_load(thresholds_path.read_text()) if thresholds_path.exists() else {}

    print(f"Golden set: {len(golden)} cases")
    print(f"RAG thresholds: {thresholds.get('rag', {})}")
    corr_cases = [c for c in golden if c.get("expected_corroboration_count") is not None]
    print(f"Corroboration-check cases: {len(corr_cases)}")
    print()
    print("To run the eval gate: uv run pytest tests/integration/test_rag_eval.py -v")


if __name__ == "__main__":
    main()
