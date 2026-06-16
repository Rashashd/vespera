"""Guardrails red-team gate: block-rate=1.0 on attacks, false-refusal=0 on legit PV controls.

Imports the rails engine directly (no live sidecar needed) so the gate is deterministic and
runnable in the CI eval job. Reads thresholds from eval_thresholds.yaml (security block).
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from guardrails.core import rails

_ROOT = Path(__file__).resolve().parent.parent.parent
_GOLDEN_SET = _ROOT / "tests" / "data" / "guardrails_redteam.jsonl"
_THRESHOLDS = _ROOT / "eval_thresholds.yaml"


def _load_cases() -> list[dict]:
    with _GOLDEN_SET.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _load_thresholds() -> dict:
    with _THRESHOLDS.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)["security"]


def test_redteam_block_rate_and_false_refusal():
    """Every attack is blocked; no legitimate PV control is refused (SC-001/SC-002)."""
    cases = _load_cases()
    assert cases, "red-team golden set is empty"

    attacks = [c for c in cases if c["expect"] == "block"]
    controls = [c for c in cases if c["expect"] == "allow"]
    assert attacks and controls, "golden set must contain both attacks and controls"

    blocked_attacks = 0
    false_refusals = 0
    for case in cases:
        result = rails.evaluate(case["text"], case["direction"], case["client_id"])
        if case["expect"] == "block":
            if result["action"] == "block":
                blocked_attacks += 1
        else:  # expect allow
            if result["action"] == "block":
                false_refusals += 1

    block_rate = blocked_attacks / len(attacks)
    thresholds = _load_thresholds()
    assert block_rate >= thresholds["guardrail_block_rate_min"], (
        f"block-rate {block_rate:.3f} < {thresholds['guardrail_block_rate_min']} "
        f"({blocked_attacks}/{len(attacks)} attacks blocked)"
    )
    assert false_refusals <= thresholds["guardrail_false_refusal_max"], (
        f"{false_refusals} legit PV control(s) wrongly refused "
        f"(max {thresholds['guardrail_false_refusal_max']})"
    )
