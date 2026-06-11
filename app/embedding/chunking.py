"""Section-aware chunking with overlap and token bounds (FR-008).

Chunking is done in pure token-ID space: encode once, slide a fixed-size window over the
token ids, and decode each window exactly once. This guarantees forward progress and a hard
upper bound on every chunk's token count — earlier code decoded then re-encoded text inside a
``while count_tokens(...) > max`` loop, which never terminated when decode→encode wasn't
length-stable (e.g. out-of-vocabulary text that decodes to ``[UNK] [UNK] ...``).
"""

import structlog

from app.embedding.enums import ChunkType
from app.embedding.parsers.base import ParsedChunk
from app.embedding.tokenizer import EmbedderTokenizer

logger = structlog.get_logger(__name__)

# Mirror EmbedderTokenizer.count_tokens' special-token reserve so a window's reported
# count (len(ids) + reserve) never exceeds max_tokens.
_RESERVE = 2


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
            max_tokens: Hard cap; chunks never exceed this (incl. the special-token reserve).
        """
        self.tokenizer = tokenizer
        self.target_tokens = target_tokens
        self.overlap_tokens = int(target_tokens * overlap_ratio)
        self.max_tokens = max_tokens

    def chunk(self, chunks: list[ParsedChunk]) -> list[ParsedChunk]:
        """Apply size-based splitting to parsed chunks, assigning sequential ordinals.

        Structural chunks (table, figure_caption) are kept whole unless they exceed the hard
        cap, in which case they are split with NO overlap. Text/structured_data chunks are
        split into ~target_tokens windows with ~overlap_tokens of overlap.

        Args:
            chunks: List of ParsedChunk from a parser.

        Returns:
            List of ParsedChunk after splitting, with updated 0-based ordinals.
        """
        result: list[ParsedChunk] = []
        for chunk in chunks:
            for text in self._split_one(chunk):
                result.append(
                    ParsedChunk(
                        text=text,
                        chunk_type=chunk.chunk_type,
                        section=chunk.section,
                        ordinal=len(result),
                    )
                )
        return result

    def _split_one(self, chunk: ParsedChunk) -> list[str]:
        """Return the chunk's text split into one or more pieces that fit the token budget."""
        if not chunk.text.strip():
            return []

        ids = self.tokenizer.tokenizer.encode(chunk.text).ids
        cap = self.max_tokens - _RESERVE  # raw-id budget that keeps count_tokens <= max_tokens
        structural = chunk.chunk_type in (ChunkType.TABLE, ChunkType.FIGURE_CAPTION)

        if structural:
            if len(ids) <= cap:
                return [chunk.text]  # keep structural chunks verbatim
            logger.warning(
                "oversized structural chunk; hard-splitting at token boundary",
                chunk_type=str(chunk.chunk_type),
                max_tokens=self.max_tokens,
            )
            return self._window_ids(ids, window=cap, step=cap)  # no overlap

        # Text / structured_data: keep small chunks verbatim, otherwise window with overlap.
        if len(ids) <= self.target_tokens:
            return [chunk.text]
        window = min(self.target_tokens, cap)
        step = max(1, window - self.overlap_tokens)
        return self._window_ids(ids, window=window, step=step)

    def _window_ids(self, ids: list[int], window: int, step: int) -> list[str]:
        """Slide a fixed window over token ids, decoding each once. Always terminates."""
        pieces: list[str] = []
        start = 0
        n = len(ids)
        while start < n:
            sub = ids[start : start + window]
            text = self.tokenizer.tokenizer.decode(sub, skip_special_tokens=True).strip()
            if text:
                # decode→re-encode is not length-stable for out-of-vocab text (it can decode
                # to "[UNK] [UNK] ..." that re-tokenizes into several tokens each), so enforce
                # the cap on the actual stored text that count_tokens will measure.
                pieces.extend(self._enforce_cap(text))
            if start + window >= n:
                break
            start += step
        return pieces

    def _enforce_cap(self, text: str) -> list[str]:
        """Guarantee count_tokens(piece) <= max_tokens by halving text until it fits."""
        if self.tokenizer.count_tokens(text) <= self.max_tokens:
            return [text]
        mid = len(text) // 2
        if mid == 0:
            return [text]  # single char already over cap: nothing more we can split
        left = text[:mid].strip()
        right = text[mid:].strip()
        out: list[str] = []
        if left:
            out.extend(self._enforce_cap(left))
        if right:
            out.extend(self._enforce_cap(right))
        return out or [text]
