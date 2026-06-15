"""Due-selection eval (spec 11 T026): precision=1.0 / recall=1.0 required.

Run:
    uv run python eval/scheduling/run_due_selection_eval.py

Scores the `is_due` golden fixture set against thresholds in eval_thresholds.yaml.
Pure-Python — no DB, no fixtures, no pytest dependency.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.scheduling.due import cadence_interval_end, compute_period, is_due  # noqa: E402

# ── Golden fixture set ─────────────────────────────────────────────────────────
# Each entry: (cadence, last_completed_at, now, expected_due, label)
# "expected_due" is the ground-truth label; we score TP/FP/TN/FN.

_ANCHOR = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)


def _days(d: int) -> timedelta:
    return timedelta(days=d)


FIXTURES: list[tuple[str, datetime | None, datetime, bool, str]] = [
    # ── Never-run (always due) ────────────────────────────────────────────────
    ("daily", None, _ANCHOR, True, "never-run daily"),
    ("weekly", None, _ANCHOR, True, "never-run weekly"),
    ("monthly", None, _ANCHOR, True, "never-run monthly"),
    # ── Exact boundary (≥ next_due → due) ────────────────────────────────────
    ("weekly", _ANCHOR - _days(7), _ANCHOR, True, "weekly exact boundary"),
    ("daily", _ANCHOR - _days(1), _ANCHOR, True, "daily exact boundary"),
    ("biweekly", _ANCHOR - _days(14), _ANCHOR, True, "biweekly exact boundary"),
    ("monthly", datetime(2026, 5, 10, 12, 0, tzinfo=UTC), _ANCHOR, True, "monthly exact boundary"),
    # ── One second past boundary ──────────────────────────────────────────────
    ("weekly", _ANCHOR - _days(7) - timedelta(seconds=1), _ANCHOR, True, "weekly one-sec overdue"),
    ("daily", _ANCHOR - _days(1) - timedelta(seconds=1), _ANCHOR, True, "daily one-sec overdue"),
    # ── Overdue by multiple intervals (coalescing: still 1 cycle) ─────────────
    ("weekly", _ANCHOR - _days(31), _ANCHOR, True, "weekly overdue 4+ intervals"),
    ("daily", _ANCHOR - _days(10), _ANCHOR, True, "daily overdue 10 intervals"),
    (
        "monthly",
        datetime(2026, 1, 1, tzinfo=UTC),
        _ANCHOR,
        True,
        "monthly overdue 5 months",
    ),
    # ── Not yet due ───────────────────────────────────────────────────────────
    ("weekly", _ANCHOR - _days(5), _ANCHOR, False, "weekly 5d ago not due"),
    ("daily", _ANCHOR - timedelta(hours=23), _ANCHOR, False, "daily 23h ago not due"),
    ("biweekly", _ANCHOR - _days(13), _ANCHOR, False, "biweekly 13d ago not due"),
    (
        "monthly",
        datetime(2026, 6, 1, tzinfo=UTC),
        _ANCHOR,
        False,
        "monthly 9d ago not due",
    ),
    # ── Jan 31 month-clamp edge ───────────────────────────────────────────────
    (
        "monthly",
        datetime(2026, 1, 31, tzinfo=UTC),
        datetime(2026, 2, 28, tzinfo=UTC),
        True,
        "monthly jan31 clamped to feb28 boundary",
    ),
    (
        "monthly",
        datetime(2026, 1, 31, tzinfo=UTC),
        datetime(2026, 2, 27, tzinfo=UTC),
        False,
        "monthly jan31 one-day before feb28 not due",
    ),
]


def _score() -> dict[str, float]:
    tp = tn = fp = fn = 0
    failures: list[str] = []
    for cadence, last, now, expected, label in FIXTURES:
        got = is_due(cadence=cadence, last_completed_at=last, now=now)
        if got == expected:
            if expected:
                tp += 1
            else:
                tn += 1
        else:
            failures.append(f"  FAIL {label!r}: expected {expected}, got {got}")
            if expected:
                fn += 1
            else:
                fp += 1

    precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
    return {
        "precision": precision,
        "recall": recall,
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "failures": failures,  # type: ignore[dict-item]
    }


def _load_thresholds() -> dict:
    path = ROOT / "eval_thresholds.yaml"
    with path.open() as f:
        return yaml.safe_load(f)["scheduling"]


def main() -> int:
    thresholds = _load_thresholds()
    result = _score()

    precision_min = thresholds["due_selection_precision_min"]
    recall_min = thresholds["due_selection_recall_min"]

    print(f"Due-selection eval  ({len(FIXTURES)} fixtures)")
    print(f"  TP={result['tp']}  TN={result['tn']}  FP={result['fp']}  FN={result['fn']}")
    print(f"  precision={result['precision']:.3f} (min {precision_min})")
    print(f"  recall={result['recall']:.3f} (min {recall_min})")

    if result["failures"]:
        print("Failures:")
        for line in result["failures"]:
            print(line)

    passed = result["precision"] >= precision_min and result["recall"] >= recall_min
    print("PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
