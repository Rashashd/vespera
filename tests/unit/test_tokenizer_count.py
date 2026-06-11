"""Unit tests for tokenizer token counting (FR-025)."""

import pytest

from app.embedding.tokenizer import EmbedderTokenizer, TokenizerError


class TestTokenizerCount:
    """Test exact token counts via the embedder tokenizer."""

    @pytest.fixture
    def tokenizer(self) -> EmbedderTokenizer:
        """Load the embedder tokenizer from the configured path."""
        # In CI, this path is relative to the repo root
        path = "modelserver/models/tokenizer.json"
        return EmbedderTokenizer(tokenizer_path=path)

    def test_count_simple_text(self, tokenizer: EmbedderTokenizer) -> None:
        """Test token counting on simple English text."""
        text = "The patient was diagnosed with diabetes."
        count = tokenizer.count_tokens(text)
        # Should be ~7 base tokens + 2 reserve = ~9
        assert count > 0
        assert count < 20

    def test_count_longer_text(self, tokenizer: EmbedderTokenizer) -> None:
        """Test token counting on longer medical text."""
        text = (
            "Adverse events were documented in the clinical trial. "
            "The patient reported dizziness, headache, and mild nausea."
        )
        count = tokenizer.count_tokens(text)
        # Should be ~25 tokens + 2 reserve
        assert count > 20

    def test_count_empty_text(self, tokenizer: EmbedderTokenizer) -> None:
        """Test token counting on empty text."""
        count = tokenizer.count_tokens("")
        # Empty text + 2 reserve
        assert count == 2

    def test_token_count_includes_reserve(self, tokenizer: EmbedderTokenizer) -> None:
        """Test that special-token reserve is included in count."""
        # The reserve should be 2 tokens
        text = "test"
        count = tokenizer.count_tokens(text)
        base_tokens = len(tokenizer.tokenizer.encode(text).ids)
        assert count == base_tokens + 2

    def test_nonexistent_tokenizer_raises_error(self) -> None:
        """Test that missing tokenizer raises TokenizerError."""
        with pytest.raises(TokenizerError):
            EmbedderTokenizer(tokenizer_path="/nonexistent/path/tokenizer.json")
