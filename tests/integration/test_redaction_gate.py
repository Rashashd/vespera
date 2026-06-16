"""Redaction gate: planted PII + secrets never survive any egress; clinical signal preserved.

Each golden-set case names the egress point and applies that point's real redaction control:
  - llm / summary / config  → redact() (full Presidio)
  - log                     → scrub_text() (the fast log/trace scrubber)
Asserts security.redaction_leak_max (0) leaked tokens and zero over-redaction of clinical terms.
The config cases satisfy FR-009a (no egress path exempt — config-derived text is redacted too).
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from app.redaction import redact, scrub_text

_ROOT = Path(__file__).resolve().parent.parent.parent
_GOLDEN_SET = _ROOT / "tests" / "data" / "redaction_golden_set.jsonl"
_THRESHOLDS = _ROOT / "eval_thresholds.yaml"


def _load_cases() -> list[dict]:
    with _GOLDEN_SET.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _apply(egress: str, text: str) -> str:
    return scrub_text(text) if egress == "log" else redact(text).text


def test_no_pii_or_secret_survives_any_egress():
    cases = _load_cases()
    assert cases, "redaction golden set is empty"
    # FR-009a: at least one config-derived case must be present (no egress exempt).
    assert any(c["egress"] == "config" for c in cases)

    with _THRESHOLDS.open(encoding="utf-8") as fh:
        leak_max = yaml.safe_load(fh)["security"]["redaction_leak_max"]

    leaks: list[str] = []
    over_redactions: list[str] = []
    for case in cases:
        out = _apply(case["egress"], case["text"])
        for token in case.get("leak_tokens", []):
            if token in out:
                leaks.append(f"{case['egress']}:{token}")
        for token in case.get("keep_tokens", []):
            if token not in out:
                over_redactions.append(f"{case['egress']}:{token}")

    assert len(leaks) <= leak_max, f"PII/secret survived egress: {leaks}"
    assert not over_redactions, f"clinical signal over-redacted (FR-011): {over_redactions}"
