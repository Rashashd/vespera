"""Secret-scan test: gitleaks finds no secrets in the working tree (US2 / SC-003)."""

import shutil
import subprocess

import pytest

pytestmark = pytest.mark.skipif(
    shutil.which("gitleaks") is None,
    reason="gitleaks binary not installed (runs in CI via gitleaks-action)",
)


def test_no_secrets_detected():
    """gitleaks reports zero findings over the working tree."""
    result = subprocess.run(
        ["gitleaks", "detect", "--no-banner", "--redact"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"gitleaks found secrets:\n{result.stdout}\n{result.stderr}"
