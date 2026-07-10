"""Enforce the constitution's >=95% coverage bar on the safety-critical paths (Cluster 5).

The 80% *global* gate lives in pyproject ([tool.coverage.report] fail_under). The constitution
("Testing gates") additionally requires >=95% on the classifier path, HITL, auth, and DB-write
paths. coverage's single `fail_under` can't express a second, path-scoped threshold, so this
script reads the coverage JSON produced from the main run's `.coverage` and enforces >=95% on
each listed module. The check is PER-MODULE on purpose: an aggregate would let a fully-covered
file mask a weak neighbour, which is exactly the kind of hole the audit (T1/T2) found in triage.

Usage:  python scripts/check_critical_coverage.py [coverage.json]
Exit 0 if every critical module is >=95%; exit 1 (listing offenders) otherwise.
"""

from __future__ import annotations

import json
import sys

THRESHOLD = 95.0

# Constitution "Testing gates": >=95% on classifier / HITL / auth / DB-write paths.
# Grouped by category for readability; enforcement is per-module. Signed off in Cluster 5 as
# the "production worthy" safety-complete set (the full triage decision chain, not just the
# classifier call, because a mis-severity / mis-routing is itself a patient-safety failure).
CRITICAL_MODULES: dict[str, list[str]] = {
    "classifier": [
        "app/triage/classify.py",
        "app/triage/service.py",
        "app/triage/llm.py",
        "app/triage/runner.py",
        "app/triage/sweep.py",
        "app/triage/severity.py",
        "app/triage/routing.py",
        "app/triage/prefilter.py",
        "app/triage/ner.py",
        "app/triage/triage_trigger.py",
    ],
    "hitl": [
        # The reviewer approve/edit/reject/discard state machine (the human-in-the-loop gate).
        "app/reports/review.py",
    ],
    "agent": [
        # The bounded drafting graph: agent loop, tool_node, escalation on caps/guard-block/error.
        "app/agent/graph.py",
    ],
    "auth": [
        "app/auth/dependencies.py",
        "app/auth/manager.py",
        "app/auth/backend.py",
        "app/auth/rate_limit.py",
    ],
    "db_write": [
        "app/audit/handler.py",
    ],
}


def required_modules() -> list[str]:
    """Flat list of every critical module across all categories."""
    return [module for group in CRITICAL_MODULES.values() for module in group]


def _norm(path: str) -> str:
    """Normalize path separators so Windows/Linux coverage keys compare equal."""
    return path.replace("\\", "/")


def load_percentages(coverage_report: dict) -> dict[str, float]:
    """Map normalized file path -> percent_covered from a `coverage json` report."""
    files = coverage_report.get("files", {})
    return {_norm(path): data["summary"]["percent_covered"] for path, data in files.items()}


def find_violations(
    percentages: dict[str, float], required: list[str], threshold: float
) -> list[tuple[str, str]]:
    """Return (module, reason) for each required module missing or below threshold."""
    violations: list[tuple[str, str]] = []
    for module in required:
        key = _norm(module)
        if key not in percentages:
            violations.append((module, "no coverage data (module never imported by any test)"))
        elif percentages[key] < threshold:
            violations.append((module, f"{percentages[key]:.2f}% < {threshold:.0f}%"))
    return violations


def main(argv: list[str]) -> int:
    path = argv[1] if len(argv) > 1 else "coverage.json"
    with open(path, encoding="utf-8") as handle:
        report = json.load(handle)
    percentages = load_percentages(report)
    required = required_modules()
    violations = find_violations(percentages, required, THRESHOLD)
    if violations:
        print(f"Critical-path coverage gate FAILED (threshold {THRESHOLD:.0f}%):")
        for module, reason in violations:
            print(f"  - {module}: {reason}")
        return 1
    print(
        f"Critical-path coverage gate PASSED: {len(required)} modules all " f">= {THRESHOLD:.0f}%."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
