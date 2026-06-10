"""Europe PMC JATS XML parser."""

from lxml import etree  # type: ignore

from app.embedding.enums import ChunkType
from app.embedding.parsers.base import ParsedChunk


class EuropePMCParser:
    """Parse Europe PMC JATS XML (same structure as PubMed)."""

    def parse(self, raw_payload: str | dict) -> list[ParsedChunk]:
        """Parse JATS XML from Europe PMC into chunks (same as PubMed for now)."""
        if isinstance(raw_payload, dict):
            raise ValueError("Europe PMC parser expects XML string")

        # Delegate to PubMed parser (same JATS format)
        from app.embedding.parsers.pubmed_jats import PubMedParser

        return PubMedParser().parse(raw_payload)

