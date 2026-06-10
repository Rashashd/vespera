"""Vault secret loading and SHA-256 artifact validation for the modelserver.

Startup validation refuses boot on missing or tampered artifacts (FR-010/US4).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import hvac

from modelserver.config import ModelserverConfig
from modelserver.logging import get_logger

_log = get_logger(__name__)


def load_modelserver_token(config: ModelserverConfig) -> str:
    """Return the service token; use config/env if set, otherwise load from Vault.

    Raises RuntimeError to abort boot if the token is empty after all attempts.
    """
    if config.modelserver_token:
        _log.info("modelserver.token.loaded", source="config")
        return config.modelserver_token

    client = hvac.Client(url=config.vault_addr, token=config.vault_token)
    try:
        authenticated = client.is_authenticated()
    except Exception as exc:
        raise RuntimeError(f"Cannot reach Vault at {config.vault_addr}: {exc}") from exc
    if not authenticated:
        raise RuntimeError("Cannot authenticate with Vault")

    try:
        data = client.secrets.kv.v2.read_secret_version(
            path=config.vault_secret_path, raise_on_deleted_version=True
        )["data"]["data"]
    except Exception as exc:
        raise RuntimeError(f"Failed to read secrets from Vault: {exc}") from exc

    token = data.get("modelserver_token", "")
    if not token:
        raise RuntimeError("modelserver_token is required but missing from Vault")

    _log.info("modelserver.token.loaded", source="vault")
    return token


def _file_sha256(path: Path) -> str:
    """Return the hex SHA-256 digest of a file."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def validate_artifacts(model_dir: Path, manifest: dict) -> None:
    """Validate every artifact's SHA-256 against the manifest.

    Raises RuntimeError on any mismatch or missing file so the service refuses
    to boot (FR-010/US4 — partial artifacts are also refused).
    """
    artifacts = manifest.get("artifacts", [])
    if not artifacts:
        raise RuntimeError("Manifest contains no artifacts — refusing to boot")

    for artifact in artifacts:
        name = artifact["name"]
        file_rel = artifact["file"]
        expected_sha = artifact["sha256"]
        path = model_dir / file_rel

        if not path.exists():
            raise RuntimeError(f"Artifact '{name}' ({file_rel}) is missing from {model_dir}")

        actual_sha = _file_sha256(path)
        if actual_sha != expected_sha:
            raise RuntimeError(
                f"Artifact '{name}' ({file_rel}) SHA-256 mismatch: "
                f"expected {expected_sha!r}, got {actual_sha!r}"
            )
        _log.info("artifact.validated", name=name, file=file_rel)

    _log.info("startup.artifact_validation.passed", count=len(artifacts))
