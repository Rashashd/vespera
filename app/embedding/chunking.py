"""Section-aware chunking with overlap and token bounds."""

import re

import structlog

from app.embedding.enums import ChunkType
from app.embedding.parsers.base import ParsedChunk
from app.embedding.tokenizer import EmbedderTokenizer

logger = structlog.get_logger(__name__)


class Chunker:
    """Section-aware text chunker with token-based size and overlap (FR-008)."""

    def __init__(
        self,
        tokenizer: EmbedderTokenizer,
        target_tokens: int = 256,
        overlap_ratio: float = 0.15,
        max_tokens: int = 512,
    ) -> None:
        """Initialize the chunker with token budget and overlap.

        Args:
            tokenizer: EmbedderTokenizer instance for accurate token counting.
            target_tokens: Target chunk size in tokens (approximate).
            overlap_ratio: Overlap as a fraction of target (e.g., 0.15 = 15%).
            max_tokens: Hard cap; chunks never exceed this.
        """
        self.tokenizer = tokenizer
        self.target_tokens = target_tokens
        self.overlap_tokens = int(target_tokens * overlap_ratio)
        self.max_tokens = max_tokens

    def chunk(self, chunks: list[ParsedChunk]) -> list[ParsedChunk]:
        """Apply chunking to parsed chunks (respects section boundaries and structural types).

        Structural chunks (table, figure_caption) are exempt from overlap.
        Oversized chunks are split at token boundaries.

        Args:
            chunks: List of ParsedChunk from a parser.

        Returns:
            List of ParsedChunk after size-based splitting, with updated ordinals.
        """
        result = []
        current_ordinal = 0

        for chunk in chunks:
            # Structural chunks (table, figure_caption) are NOT split and do NOT have overlap
            if chunk.chunk_type in (ChunkType.TABLE, ChunkType.FIGURE_CAPTION):
                if self._is_oversized(chunk.text):
                    # Hard-split at token boundary as last resort
                    sub_chunks = self._hard_split_oversized(
                        chunk.text, chunk.chunk_type, chunk.section
                    )
                    for sub_chunk in sub_chunks:
                        sub_chunk.ordinal = current_ordinal
                        current_ordinal += 1
                        result.append(sub_chunk)
                else:
                    chunk.ordinal = current_ordinal
                    current_ordinal += 1
                    result.append(chunk)
            else:
                # Text and structured_data chunks use overlap-based splitting
                split_chunks = self._split_text_chunk(chunk.text, chunk.chunk_type, chunk.section)
                for sub_chunk in split_chunks:
                    sub_chunk.ordinal = current_ordinal
                    current_ordinal += 1
                    result.append(sub_chunk)

        return result

    def _is_oversized(self, text: str) -> bool:
        """Check if text exceeds the hard cap."""
        return self.tokenizer.count_tokens(text) > self.max_tokens

    def _hard_split_oversized(
        self, text: str, chunk_type: ChunkType, section: str | None
    ) -> list[ParsedChunk]:
        """Split an oversized chunk at token boundaries (hard cap enforcement).

        Prefers table-row boundaries; falls back to any token boundary.
        Logs a warning when this occurs.
        """
        logger.warning(
            f"Oversized {chunk_type} chunk (exceeds {self.max_tokens} tokens); "
            "splitting at token boundary"
        )
        result = []
        remaining = text
        chunk_order = 0

        while remaining:
            # Try to fit up to max_tokens
            split = self._split_at_token_boundary(remaining, max_tokens=self.max_tokens)
            chunk_text, remaining = split

            result.append(
                ParsedChunk(
                    text=chunk_text,
                    chunk_type=chunk_type,
                    section=section,
                    ordinal=chunk_order,
                )
            )
            chunk_order += 1

        return result

    def _split_text_chunk(
        self, text: str, chunk_type: ChunkType, section: str | None
    ) -> list[ParsedChunk]:
        """Split text chunk with overlap (target → max_tokens cap)."""
        result = []
        remaining = text
        chunk_order = 0
        overlap_buffer = ""

        while remaining:
            # Target size with overlap
            chunk_text, remaining = self._split_at_token_boundary(
                overlap_buffer + remaining,
                max_tokens=self.target_tokens,
            )

            # Remove overlap prefix from displayed chunk (keep text, not in result yet)
            if chunk_order > 0:
                # Remove the leading overlap portion from display
                if len(overlap_buffer) > 0 and chunk_text.startswith(overlap_buffer):
                    chunk_text = chunk_text[len(overlap_buffer) :]
                    # Re-verify after string slicing (token boundaries don't match char boundaries)
                    while self.tokenizer.count_tokens(chunk_text) > self.max_tokens and chunk_text:
                        chunk_text, _ = self._split_at_token_boundary(
                            chunk_text, max_tokens=self.max_tokens
                        )

            result.append(
                ParsedChunk(
                    text=chunk_text,
                    chunk_type=chunk_type,
                    section=section,
                    ordinal=chunk_order,
                )
            )

            # Prepare overlap for next iteration
            if remaining:
                overlap_buffer = self._get_overlap_suffix(chunk_text)
                chunk_order += 1

        return result

    def _split_at_token_boundary(self, text: str, max_tokens: int) -> tuple[str, str]:
        """Split text at a token boundary, respecting sentence boundaries when possible.

        Returns:
            (chunk_text, remaining_text)
        """
        tokens = self.tokenizer.tokenizer.encode(text)
        if len(tokens.ids) <= max_tokens:
            return text, ""

        # Take up to max_tokens; decode back to text
        limited_ids = tokens.ids[:max_tokens]
        chunk_text = self.tokenizer.tokenizer.decode(limited_ids, skip_special_tokens=True)

        # Find the last sentence boundary within the chunk
        last_match = None
        for match in re.finditer(r"[.!?]\s", chunk_text):
            last_match = match

        if last_match:
            # Split at last sentence boundary
            split_pos = last_match.end()
            return chunk_text[:split_pos], text[split_pos:].strip()
        else:
            # No sentence boundary; return the decoded chunk and remaining original text
            # Find approximately where the decoded text ends in the original (best effort)
            # by looking for the last few words of chunk_text in the original
            chunk_tokens_count = len(limited_ids)
            remaining_tokens = tokens.ids[chunk_tokens_count:]
            remaining_text = self.tokenizer.tokenizer.decode(
                remaining_tokens, skip_special_tokens=True
            )
            return chunk_text, remaining_text.strip()

    def _get_overlap_suffix(self, chunk_text: str, overlap_tokens: int | None = None) -> str:
        """Extract a suffix of the chunk for overlap into the next chunk."""
        if overlap_tokens is None:
            overlap_tokens = self.overlap_tokens

        tokens = self.tokenizer.tokenizer.encode(chunk_text)
        if len(tokens.ids) <= overlap_tokens:
            return chunk_text

        # Take the last overlap_tokens
        overlap_ids = tokens.ids[-overlap_tokens:]
        return self.tokenizer.tokenizer.decode(overlap_ids, skip_special_tokens=True)
