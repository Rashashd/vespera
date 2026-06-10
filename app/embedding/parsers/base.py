"""Parser protocol and ParsedChunk dataclass."""

from dataclasses import dataclass
from typing import Protocol

from app.embedding.enums import ChunkType


@dataclass
class ParsedChunk:
    """Output from a parser (before embedding / metadata attachment)."""

    text: str
    chunk_type: ChunkType
    section: str | None = None
    ordinal: int = 0


class Parser(Protocol):
    """Parser contract: takes raw payload (str/dict) and returns list[ParsedChunk]."""

    def parse(self, raw_payload: str | dict) -> list[ParsedChunk]:
        """Parse a raw payload (JATS XML string, JSON dict, etc) into typed chunks.

        Args:
            raw_payload: The raw document payload from DocumentSource.raw_payload.

        Returns:
            List of ParsedChunk with text, chunk_type, and optional section.

        Raises:
            ParseError: If the payload cannot be parsed (transient vs permanent logged separately).
        """
        ...
