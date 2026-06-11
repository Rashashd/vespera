"""Load and expose model-version identifiers from the committed manifest.json (D4/D9)."""

from __future__ import annotations

import json
from pathlib import Path


class Manifest:
    """Parsed model manifest: artifact metadata and per-artifact version identifiers."""

    def __init__(self, model_dir: Path) -> None:
        path = model_dir / "manifest.json"
        self._data: dict = json.loads(path.read_text())
        self._by_name: dict[str, dict] = {a["name"]: a for a in self._data.get("artifacts", [])}

    def artifact(self, name: str) -> dict:
        """Return the manifest entry for the named artifact; raise KeyError if absent."""
        if name not in self._by_name:
            raise KeyError(f"Artifact '{name}' not found in manifest")
        return self._by_name[name]

    def model_version(self, name: str) -> dict:
        """Return the model-version identifier dict for a named artifact (FR-005b/D9)."""
        a = self.artifact(name)
        return {"name": a["name"], "version": a["version"], "sha256": a["sha256"]}

    @property
    def raw(self) -> dict:
        """The full parsed manifest dict."""
        return self._data
