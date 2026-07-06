"""The >=95% critical-path coverage gate must actually bite (Cluster 5 / spec sanity check).

Confirms find_violations flags a module dropped below the threshold or missing entirely, and
passes a fully-covered set — so a regression that stops covering a critical-path line reddens
CI instead of slipping through. Imports the checker by path (scripts/ is not a package).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_critical_coverage.py"


def _load_gate():
    spec = importlib.util.spec_from_file_location("check_critical_coverage", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load_gate()


def test_all_green_passes():
    required = gate.required_modules()
    percentages = {module: 100.0 for module in required}
    assert gate.find_violations(percentages, required, gate.THRESHOLD) == []


def test_exactly_at_threshold_passes():
    required = gate.required_modules()
    percentages = {module: gate.THRESHOLD for module in required}
    assert gate.find_violations(percentages, required, gate.THRESHOLD) == []


def test_below_threshold_module_is_flagged():
    required = gate.required_modules()
    percentages = {module: 100.0 for module in required}
    percentages[required[0]] = 94.99  # drop one critical module just under the bar
    violations = gate.find_violations(percentages, required, gate.THRESHOLD)
    assert [module for module, _ in violations] == [required[0]]


def test_missing_module_is_flagged():
    required = gate.required_modules()
    percentages = {module: 100.0 for module in required}
    del percentages[required[0]]  # module never imported by any test -> no data
    violations = gate.find_violations(percentages, required, gate.THRESHOLD)
    assert required[0] in [module for module, _ in violations]


def test_load_percentages_normalizes_windows_paths():
    report = {"files": {"app\\triage\\ner.py": {"summary": {"percent_covered": 97.5}}}}
    assert gate.load_percentages(report) == {"app/triage/ner.py": 97.5}
