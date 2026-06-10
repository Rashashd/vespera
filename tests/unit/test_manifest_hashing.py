"""Unit tests for startup artifact SHA-256 validation (US4 / T030).

Covers: correct SHA-256 passes; wrong SHA-256 raises RuntimeError; missing file
raises RuntimeError; empty artifact list raises RuntimeError; partial list (one
artifact absent) raises RuntimeError.
"""

from __future__ import annotations

import hashlib

import pytest

from modelserver.startup import validate_artifacts


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(path, data: bytes) -> None:
    path.write_bytes(data)


# ---------------------------------------------------------------------------
# Passing cases
# ---------------------------------------------------------------------------


def test_valid_single_artifact_passes(tmp_path):
    data = b"model bytes"
    f = tmp_path / "model.bin"
    _write(f, data)
    manifest = {"artifacts": [{"name": "clf", "file": "model.bin", "sha256": _sha256(data)}]}
    validate_artifacts(tmp_path, manifest)  # must not raise


def test_valid_multiple_artifacts_pass(tmp_path):
    files = {"a.bin": b"aaa", "b.bin": b"bbb", "c.bin": b"ccc"}
    for name, data in files.items():
        _write(tmp_path / name, data)
    manifest = {
        "artifacts": [{"name": n, "file": n, "sha256": _sha256(d)} for n, d in files.items()]
    }
    validate_artifacts(tmp_path, manifest)


# ---------------------------------------------------------------------------
# Failure cases
# ---------------------------------------------------------------------------


def test_sha256_mismatch_raises(tmp_path):
    f = tmp_path / "model.bin"
    _write(f, b"original")
    manifest = {
        "artifacts": [{"name": "clf", "file": "model.bin", "sha256": _sha256(b"different")}]
    }
    with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
        validate_artifacts(tmp_path, manifest)


def test_missing_file_raises(tmp_path):
    manifest = {"artifacts": [{"name": "clf", "file": "missing.bin", "sha256": "deadbeef"}]}
    with pytest.raises(RuntimeError, match="missing"):
        validate_artifacts(tmp_path, manifest)


def test_empty_artifact_list_raises(tmp_path):
    with pytest.raises(RuntimeError, match="no artifacts"):
        validate_artifacts(tmp_path, {"artifacts": []})


def test_missing_artifacts_key_raises(tmp_path):
    with pytest.raises(RuntimeError, match="no artifacts"):
        validate_artifacts(tmp_path, {})


def test_partial_list_second_artifact_missing_raises(tmp_path):
    """First artifact valid; second file absent — should refuse boot."""
    good = tmp_path / "good.bin"
    _write(good, b"good data")
    manifest = {
        "artifacts": [
            {"name": "good", "file": "good.bin", "sha256": _sha256(b"good data")},
            {"name": "missing", "file": "missing.bin", "sha256": "00" * 32},
        ]
    }
    with pytest.raises(RuntimeError, match="missing"):
        validate_artifacts(tmp_path, manifest)


def test_tampered_file_raises(tmp_path):
    """Write correct file, build manifest, then tamper the file."""
    f = tmp_path / "model.bin"
    _write(f, b"original bytes")
    manifest = {
        "artifacts": [{"name": "clf", "file": "model.bin", "sha256": _sha256(b"original bytes")}]
    }
    # Tamper
    _write(f, b"tampered bytes")
    with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
        validate_artifacts(tmp_path, manifest)
