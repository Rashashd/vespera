"""Pure normalized-identifier helpers: DOI → PMID → <source>:<id> precedence (D4)."""

from __future__ import annotations

from app.ingestion.enums import SourceName


def normalize_id(
    *,
    doi: str | None,
    pmid: str | None,
    source: SourceName,
    source_external_id: str,
) -> str | None:
    """Return the canonical dedup key, or None if no identifier can be derived.

    Precedence: doi > pmid > source-namespaced id. All values are lowercased and stripped so
    the same real paper matches regardless of how different adapters report it.
    """
    if doi and doi.strip():
        return f"doi:{doi.strip().lower()}"
    if pmid and pmid.strip():
        return f"pmid:{pmid.strip().lower()}"
    sid = source_external_id.strip()
    if sid:
        return f"{source.value}:{sid.lower()}"
    return None
