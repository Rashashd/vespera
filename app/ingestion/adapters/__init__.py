"""Adapter contract: RawRecord, WatchlistQuery, SourceAdapter Protocol, ENABLED_ADAPTERS."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from app.ingestion.enums import SourceName, SourceReliability


@dataclass(frozen=True)
class RawRecord:
    """Common shape an adapter produces per external record (FR-004, contracts/)."""

    source: SourceName
    source_external_id: str
    raw_payload: dict
    doi: str | None = None
    pmid: str | None = None
    title: str | None = None
    summary: str | None = None
    published_at: datetime | None = None
    origin_url: str | None = None
    # Optional record-level reliability override (used by OpenFDA which emits two tiers).
    reliability: SourceReliability | None = None


@dataclass(frozen=True)
class WatchlistQuery:
    """Read-only query the runner builds once per run from the watchlist."""

    drugs: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    mesh_terms: list[str] = field(default_factory=list)  # only valid/unvalidated (FR-010)


@runtime_checkable
class SourceAdapter(Protocol):
    """Uniform contract every source adapter implements (contracts/source-adapter.md)."""

    name: SourceName
    reliability: SourceReliability

    async def fetch(
        self,
        query: WatchlistQuery,
        since: datetime | None,
        cap: int,
    ) -> list[RawRecord]:
        """Fetch at most `cap` records matching query published after `since`."""
        ...


# Populated at import time by each adapter module (registration order = execution order).
ENABLED_ADAPTERS: list[SourceAdapter] = []
