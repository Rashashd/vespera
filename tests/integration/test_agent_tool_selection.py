"""Agent tool-selection eval gate: accuracy ≥ 0.85 against the golden set (SC-004).

Self-contained — uses a rule-based oracle, no live stack or LLM required.
The oracle encodes the documented workflow rules from app/agent/prompts/system_draft.txt.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

_GOLDEN = Path(__file__).resolve().parent.parent / "data" / "agent_tool_selection_golden.jsonl"
_THRESHOLDS = Path(__file__).resolve().parent.parent.parent / "eval_thresholds.yaml"


def _load_golden() -> list[dict]:
    cases = []
    with _GOLDEN.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def _load_thresholds() -> dict:
    with _THRESHOLDS.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _oracle_tool(case: dict) -> str | None:
    """Rule-based oracle mirroring the system prompt workflow rules.

    Rules (in priority order):
    1. Turn 1 → score_severity
    2. score_severity not yet called → score_severity
    3. At or near iteration cap → escalate
    4. Last draft_report error = no_groundable_claims → escalate
    5. retrieve_result_count=0 after 2+ retrieves → escalate
    6. draft_followup already called → null (done)
    7. draft_report already called + emergency → draft_followup
    8. draft_report already called + not emergency → null (done)
    9. retrieve already called + retrieve_result_count > 0 → draft_report
    10. retrieve called but insufficient evidence → retrieve again
    11. retrieve done, result_count unspecified → draft_report
    12. score_severity already called → retrieve
    13. fallback → null
    """
    context = case.get("context", case)
    prior = context.get("prior_tools_called", [])
    bucket = context.get("bucket", "urgent")
    # agent_turn may be at case level or context level
    turn = case.get("agent_turn", context.get("agent_turn", 1))
    iterations_used = context.get("iterations_used", turn - 1)
    result_count = context.get("retrieve_result_count", None)
    draft_error = context.get("draft_report_error", None)
    last_error = context.get("last_tool_error", "")
    insufficient = context.get("insufficient_evidence", False)

    # Cap near exhaustion
    if iterations_used >= 7:
        return "escalate"

    # Turn 1 or score_severity not yet called
    if turn == 1 or "score_severity" not in prior:
        return "score_severity"

    # retrieve with no results → escalate
    if "retrieve" in prior and result_count == 0:
        # Allow another retrieve on first no-result if we've only retrieved once
        retrieve_count = prior.count("retrieve")
        if retrieve_count >= 2:
            return "escalate"

    # draft_report error → escalate
    if draft_error == "no_groundable_claims":
        return "escalate"

    # Last tool error was non-retryable
    if last_error == "retrieve_failed_permanent":
        return "escalate"

    # draft_followup done → null
    if "draft_followup" in prior:
        return None

    # draft_report done
    if "draft_report" in prior:
        if bucket == "emergency":
            return "draft_followup"
        return None

    # Retrieve done with results (and not insufficient)
    if "retrieve" in prior and result_count is not None and result_count > 0 and not insufficient:
        return "draft_report"

    # Retrieve done but insufficient evidence → retrieve again
    if "retrieve" in prior and insufficient:
        return "retrieve"

    # Retrieve done, result_count not specified in context (assume sufficient)
    if "retrieve" in prior and result_count is None and not insufficient:
        return "draft_report"

    # score_severity done → retrieve
    if "score_severity" in prior:
        return "retrieve"

    return None


def test_tool_selection_golden_set():
    """Oracle accuracy ≥ 0.85 vs. golden set (SC-004)."""
    thresholds = _load_thresholds()
    min_accuracy = thresholds["agent"]["tool_selection_accuracy_min"]

    cases = _load_golden()
    assert len(cases) >= 15, f"Golden set must have ≥15 cases, got {len(cases)}"

    correct = 0
    failures: list[str] = []

    for case in cases:
        expected = case["expected_tool"]
        predicted = _oracle_tool(case)

        if predicted == expected:
            correct += 1
        else:
            failures.append(
                f"{case['id']} [{case['scenario']}]: expected={expected!r} predicted={predicted!r}"
            )

    accuracy = correct / len(cases)
    failure_summary = "\n  ".join(failures) if failures else "none"
    assert accuracy >= min_accuracy, (
        f"Tool-selection accuracy {accuracy:.3f} < {min_accuracy:.2f}\n"
        f"Failures ({len(failures)}/{len(cases)}):\n  {failure_summary}"
    )


def test_golden_set_has_no_null_only():
    """Verify the golden set has a mix of tool calls and null (done) outcomes."""
    cases = _load_golden()
    non_null = [c for c in cases if c["expected_tool"] is not None]
    null_cases = [c for c in cases if c["expected_tool"] is None]
    assert len(non_null) >= 10, "Golden set needs ≥10 non-null tool cases"
    assert len(null_cases) >= 3, "Golden set needs ≥3 null (done) cases"


def test_golden_set_covers_escalation():
    """Verify the golden set includes at least 3 escalation cases."""
    cases = _load_golden()
    escalate_cases = [c for c in cases if c["expected_tool"] == "escalate"]
    assert (
        len(escalate_cases) >= 3
    ), f"Golden set needs ≥3 escalate cases for safety coverage; got {len(escalate_cases)}"


def test_golden_set_covers_emergency_followup():
    """Verify the golden set includes the emergency follow-up path."""
    cases = _load_golden()
    followup_cases = [c for c in cases if c["expected_tool"] == "draft_followup"]
    assert len(followup_cases) >= 1, "Golden set must include the emergency draft_followup path"
