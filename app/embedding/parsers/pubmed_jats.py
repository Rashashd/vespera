"""PubMed JATS XML parser."""

from lxml import etree  # type: ignore

from app.embedding.enums import ChunkType
from app.embedding.parsers.base import ParsedChunk


class PubMedParser:
    """Parse PubMed JATS XML into typed chunks."""

    def parse(self, raw_payload: str | dict) -> list[ParsedChunk]:
        """Parse JATS XML from PubMed into text and structured chunks.

        Args:
            raw_payload: JATS XML string.

        Returns:
            List of ParsedChunk (text per section, metadata preserved).

        Raises:
            ParseError: If XML is malformed (caught at call site for classification).
        """
        if isinstance(raw_payload, dict):
            raise ValueError("PubMed parser expects XML string, not dict")

        if not isinstance(raw_payload, str):
            raise ValueError(f"Expected str, got {type(raw_payload)}")

        try:
            root = etree.fromstring(raw_payload.encode("utf-8"))
        except etree.XMLSyntaxError as e:
            from app.embedding.parsers.base import ParseError

            raise ParseError(f"Failed to parse JATS XML: {e}", is_transient=False) from e

        chunks = []

        # Extract article element
        article = root.find(".//Article")
        if article is None:
            return chunks

        # Article title
        title_elem = article.find("ArticleTitle")
        if title_elem is not None and title_elem.text:
            chunks.append(
                ParsedChunk(
                    text=self._normalize_text(title_elem.text),
                    chunk_type=ChunkType.TEXT,
                    section="Title",
                )
            )

        # Abstract
        abstract = article.find(".//Abstract")
        if abstract is not None:
            abstract_text_elem = abstract.find("AbstractText")
            if abstract_text_elem is not None:
                abstract_text = self._extract_text_recursive(abstract_text_elem)
                if abstract_text.strip():
                    chunks.append(
                        ParsedChunk(
                            text=abstract_text,
                            chunk_type=ChunkType.TEXT,
                            section="Abstract",
                        )
                    )

        # Body sections
        body = article.find(".//Body")
        if body is not None:
            for section in body.findall(".//Section"):
                section_title_elem = section.find("Title")
                section_name = section_title_elem.text if section_title_elem is not None else "Body"

                # Extract paragraph text from this section
                for para in section.findall(".//Paragraph"):
                    para_text = self._extract_text_recursive(para)
                    if para_text.strip():
                        chunks.append(
                            ParsedChunk(
                                text=para_text,
                                chunk_type=ChunkType.TEXT,
                                section=section_name,
                            )
                        )

                # Extract tables
                for table in section.findall(".//Table"):
                    table_text = self._extract_table_text(table)
                    if table_text.strip():
                        chunks.append(
                            ParsedChunk(
                                text=table_text,
                                chunk_type=ChunkType.TABLE,
                                section=section_name,
                            )
                        )

                # Extract figure captions
                for fig in section.findall(".//Figure"):
                    caption_elem = fig.find("Caption")
                    if caption_elem is not None:
                        caption_text = self._extract_text_recursive(caption_elem)
                        if caption_text.strip():
                            chunks.append(
                                ParsedChunk(
                                    text=caption_text,
                                    chunk_type=ChunkType.FIGURE_CAPTION,
                                    section=section_name,
                                )
                            )

        return chunks

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Normalize whitespace in text."""
        return " ".join(text.split())

    @staticmethod
    def _extract_text_recursive(element) -> str:  # type: ignore
        """Extract all text from element and descendants."""
        text_parts = []

        if element.text:
            text_parts.append(element.text)

        for child in element:
            text_parts.append(PubMedParser._extract_text_recursive(child))
            if child.tail:
                text_parts.append(child.tail)

        return " ".join(text_parts)

    @staticmethod
    def _extract_table_text(table) -> str:  # type: ignore
        """Extract table content as structured text."""
        rows = table.findall(".//Row")
        if not rows:
            return ""

        lines = []
        for row in rows:
            cols = row.findall(".//Entry")
            col_texts = [PubMedParser._extract_text_recursive(col).strip() for col in cols]
            lines.append(" | ".join(col_texts))

        return "\n".join(lines)
