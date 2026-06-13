"""OpenFDA FAERS structured parser."""

import json

from app.embedding.enums import ChunkType
from app.embedding.parsers.base import ParsedChunk


class OpenFDAFAERSParser:
    """Parse OpenFDA FAERS report into a structured data chunk."""

    def parse(self, raw_payload: str | dict) -> list[ParsedChunk]:
        """Parse FAERS report JSON into a single structured_data chunk."""
        if isinstance(raw_payload, str):
            try:
                data = json.loads(raw_payload)
            except json.JSONDecodeError as e:
                from app.embedding.parsers.base import ParseError

                raise ParseError(f"Failed to parse FAERS JSON: {e}", is_transient=False) from e
        else:
            data = raw_payload

        # Convert to natural language summary
        text_parts = []
        if isinstance(data, dict):
            if "patient" in data:
                text_parts.append(f"Patient: {data['patient']}")
            if "reaction" in data:
                text_parts.append(f"Reaction: {data['reaction']}")
            if "drug" in data:
                text_parts.append(f"Drug: {data['drug']}")
            if "outcome" in data:
                text_parts.append(f"Outcome: {data['outcome']}")

        text = " ".join(text_parts) if text_parts else str(data)[:500]

        return [
            ParsedChunk(
                text=text,
                chunk_type=ChunkType.STRUCTURED_DATA,
                section="FAERS Report",
            )
        ]
