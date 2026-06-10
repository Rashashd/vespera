"""FDA MedWatch, EMA, MHRA regulatory feed parser."""

import json

from app.embedding.enums import ChunkType
from app.embedding.parsers.base import ParsedChunk


class RegulatoryFeedParser:
    """Parse regulatory alert feeds (MedWatch, EMA, MHRA) into summary chunks."""

    def parse(self, raw_payload: str | dict) -> list[ParsedChunk]:
        """Parse regulatory alert into a single summary chunk."""
        if isinstance(raw_payload, str):
            try:
                data = json.loads(raw_payload)
            except json.JSONDecodeError as e:
                from app.embedding.router import ParseError
                raise ParseError(f"Failed to parse alert JSON: {e}", is_transient=False) from e
        else:
            data = raw_payload

        # Build a summary from available fields
        text_parts = []

        if isinstance(data, dict):
            for field in ["title", "summary", "alert_id", "date", "product"]:
                if field in data and data[field]:
                    text_parts.append(str(data[field]))

        text = " ".join(text_parts) if text_parts else str(data)[:500]

        return [
            ParsedChunk(
                text=text,
                chunk_type=ChunkType.TEXT,
                section="Regulatory Alert",
            )
        ]

