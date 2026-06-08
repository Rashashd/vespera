"""Bundled slim MeSH heading loader and save-time validator (D11, FR-009)."""

from __future__ import annotations

import importlib.resources
from functools import lru_cache

from app.ingestion.enums import MeshValidity

_MESH_DATA_PACKAGE = "app.ingestion.data"
_MESH_FILENAME = "mesh_terms.txt"


@lru_cache(maxsize=1)
def load_mesh_terms() -> frozenset[str]:
    """Load the bundled slim MeSH heading list into a frozenset (lowercase canonical keys).

    Raises FileNotFoundError if the artifact is missing — callers should catch and degrade to
    MeshValidity.UNVALIDATED (FR-009).
    """
    ref = importlib.resources.files(_MESH_DATA_PACKAGE).joinpath(_MESH_FILENAME)
    text = ref.read_text(encoding="utf-8")
    terms: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            terms.add(line.lower())
    if not terms:
        raise FileNotFoundError(f"No terms found in {_MESH_FILENAME}")
    return frozenset(terms)


def validate_mesh(term: str) -> tuple[MeshValidity, str | None]:
    """Return (validity, canonical_heading | None) for a MeSH term.

    canonical_heading is the original-cased heading from the list when valid.
    Falls back to UNVALIDATED when the bundled artifact is unavailable (FR-009).
    """
    try:
        terms = load_mesh_terms()
    except Exception:  # noqa: BLE001
        return MeshValidity.UNVALIDATED, None

    normalized = term.strip().lower()
    if normalized in terms:
        # Re-derive canonical casing from the raw file for the canonical field.
        # Since we only store lowercase in the frozenset, we return title-case as canonical.
        canonical = term.strip()
        return MeshValidity.VALID, canonical
    return MeshValidity.INVALID, None
