"""OpenFDA label JSON parser."""

import json

from app.embedding.enums import ChunkType
from app.embedding.parsers.base import ParsedChunk


class OpenFDALabelParser:
    """Parse OpenFDA drug label JSON into section-based chunks."""

    def parse(self, raw_payload: str | dict) -> list[ParsedChunk]:
        """Parse drug label JSON into section chunks."""
        if isinstance(raw_payload, str):
            try:
                data = json.loads(raw_payload)
            except json.JSONDecodeError as e:
                from app.embedding.router import ParseError

                raise ParseError(f"Failed to parse label JSON: {e}", is_transient=False) from e
        else:
            data = raw_payload

        chunks = []

        if isinstance(data, dict):
            # Extract common label sections
            sections = [
                ("indications_and_usage", "Indications and Usage"),
                ("warnings", "Warnings"),
                ("contraindications", "Contraindications"),
                ("adverse_reactions", "Adverse Reactions"),
                ("dosage_and_administration", "Dosage and Administration"),
            ]

            for key, section_name in sections:
                if key in data and data[key]:
                    text = data[key]
                    if isinstance(text, list):
                        text = " ".join(str(t) for t in text)
                    chunks.append(
                        ParsedChunk(
                            text=str(text)[:2000],  # Truncate very long sections
                            chunk_type=ChunkType.TEXT,
                            section=section_name,
                        )
                    )

        return chunks
