"""Europe PMC parser: search-API JSON metadata (dict) or JATS full-text XML (str)."""

from app.embedding.enums import ChunkType
from app.embedding.parsers.base import ParsedChunk


class EuropePMCParser:
    """Parse Europe PMC results.

    The ingestion adapter fetches the search API (``format=json``), so the stored payload is a
    metadata dict (title + abstractText, occasionally full text). When a JATS XML string is
    supplied instead (full-text fetch) we delegate to the PubMed JATS parser — the format matches.
    """

    def parse(self, raw_payload: str | dict) -> list[ParsedChunk]:
        """Parse Europe PMC into chunks: JSON metadata → title/abstract; XML → JATS."""
        # Full-text JATS XML path (same structure as PubMed).
        if isinstance(raw_payload, str):
            from app.embedding.parsers.pubmed_jats import PubMedParser

            return PubMedParser().parse(raw_payload)

        # Search-API JSON metadata: build chunks from the available fields (title + abstract).
        chunks: list[ParsedChunk] = []
        title = (raw_payload.get("title") or "").strip()
        if title:
            chunks.append(
                ParsedChunk(
                    text=" ".join(title.split()),
                    chunk_type=ChunkType.TEXT,
                    section="Title",
                )
            )
        abstract = (raw_payload.get("abstractText") or "").strip()
        if abstract:
            chunks.append(
                ParsedChunk(
                    text=" ".join(abstract.split()),
                    chunk_type=ChunkType.TEXT,
                    section="Abstract",
                )
            )
        return chunks
