"""Source selection logic for multi-source documents."""

import json
from typing import Any

from app.ingestion.enums import SourceReliability


def select_source(document_sources: list[Any]) -> Any:
    """Select the best source payload for a multi-source document (FR-024).

    Ordering: reliability (highest rank) → richness (longest payload) → recency (most recent).

    Args:
        document_sources: List of DocumentSource ORM objects.

    Returns:
        The selected DocumentSource object.

    Raises:
        ValueError: If no valid source is available.
    """
    if not document_sources:
        raise ValueError("No document sources available")

    # Sort by: reliability rank (desc), payload length (desc), fetched_at (desc)
    def sort_key(ds):  # type: ignore
        # Use document's reliability tier, not source name
        try:
            reliability_rank = SourceReliability(ds.document.source_reliability).rank
        except (ValueError, AttributeError):
            reliability_rank = -1

        # Richness: serialized payload length
        if ds.raw_payload:
            if isinstance(ds.raw_payload, dict):
                payload_length = len(json.dumps(ds.raw_payload))
            else:
                payload_length = len(ds.raw_payload)
        else:
            payload_length = 0

        fetched_at_timestamp = ds.fetched_at.timestamp() if ds.fetched_at else 0

        # Return tuple for descending sort on all three
        return (reliability_rank, payload_length, fetched_at_timestamp)

    sorted_sources = sorted(document_sources, key=sort_key, reverse=True)
    return sorted_sources[0]
