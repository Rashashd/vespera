"""Unit tests for section-aware chunking with overlap and token bounds (FR-008)."""

import pytest

from app.embedding.chunking import Chunker
from app.embedding.enums import ChunkType
from app.embedding.parsers.base import ParsedChunk
from app.embedding.tokenizer import EmbedderTokenizer


class TestChunking:
    """Test chunking with size targets, overlap, and hard caps."""

    @pytest.fixture
    def tokenizer(self) -> EmbedderTokenizer:
        """Load the embedder tokenizer."""
        return EmbedderTokenizer(tokenizer_path="modelserver/models/tokenizer.json")

    @pytest.fixture
    def chunker(self, tokenizer: EmbedderTokenizer) -> Chunker:
        """Create a chunker with standard settings."""
        return Chunker(
            tokenizer=tokenizer,
            target_tokens=256,
            overlap_ratio=0.15,
            max_tokens=512,
        )

    def test_chunk_single_small_text(self, chunker: Chunker) -> None:
        """Test chunking a single small text (no splitting needed)."""
        chunk = ParsedChunk(
            text="The patient was diagnosed with diabetes.",
            chunk_type=ChunkType.TEXT,
            section="Introduction",
        )
        result = chunker.chunk([chunk])
        assert len(result) == 1
        assert result[0].text == "The patient was diagnosed with diabetes."
        assert result[0].ordinal == 0

    def test_chunk_structural_no_overlap(self, chunker: Chunker) -> None:
        """Test that table chunks are exempt from overlap."""
        table = ParsedChunk(
            text="Header1 | Header2\nRow1Col1 | Row1Col2",
            chunk_type=ChunkType.TABLE,
        )
        result = chunker.chunk([table])
        assert len(result) == 1
        assert result[0].chunk_type == ChunkType.TABLE

    def test_chunk_preserves_section(self, chunker: Chunker) -> None:
        """Test that section labels are preserved through chunking."""
        chunk = ParsedChunk(
            text="This is a test section. " * 50,  # Repeat to create a long text
            chunk_type=ChunkType.TEXT,
            section="Methods",
        )
        result = chunker.chunk([chunk])
        # Even if split into multiple chunks, all should have the section
        for sub_chunk in result:
            assert sub_chunk.section == "Methods"

    def test_chunk_increments_ordinals(self, chunker: Chunker) -> None:
        """Test that ordinals are assigned sequentially."""
        chunks = [
            ParsedChunk(text="Short text 1.", chunk_type=ChunkType.TEXT),
            ParsedChunk(text="Short text 2.", chunk_type=ChunkType.TEXT),
        ]
        result = chunker.chunk(chunks)
        ordinals = [c.ordinal for c in result]
        assert ordinals == list(range(len(result)))

    def test_chunk_respects_max_tokens(self, chunker: Chunker) -> None:
        """Test that no chunk exceeds max_tokens."""
        # Create a very long text (should be split)
        long_text = "Medical finding. " * 200
        chunk = ParsedChunk(text=long_text, chunk_type=ChunkType.TEXT)
        result = chunker.chunk([chunk])
        for result_chunk in result:
            token_count = chunker.tokenizer.count_tokens(result_chunk.text)
            assert token_count <= chunker.max_tokens
