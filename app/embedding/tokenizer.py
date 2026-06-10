"""Tokenizer loading and token counting utilities."""

from pathlib import Path

from tokenizers import Tokenizer  # type: ignore

from app.infra.modelserver_client import ModelserverClient


class TokenizerError(Exception):
    """Raised on tokenizer loading or verification failures."""

    pass


class EmbedderTokenizer:
    """Load and use the embedder's tokenizer for accurate token counting (FR-025)."""

    def __init__(self, tokenizer_path: str) -> None:
        """Load the tokenizer from tokenizer.json."""
        path = Path(tokenizer_path)
        if not path.exists():
            raise TokenizerError(f"Tokenizer not found at {tokenizer_path}")
        try:
            self.tokenizer = Tokenizer.from_file(str(path))
        except Exception as e:
            raise TokenizerError(f"Failed to load tokenizer from {tokenizer_path}: {e}") from e

    def count_tokens(self, text: str) -> int:
        """Count tokens in text using the embedder's tokenizer + special-token reserve (FR-025)."""
        tokens = self.tokenizer.encode(text)
        # Reserve space for special tokens (e.g., [CLS], [SEP])
        reserve = 2
        return len(tokens.ids) + reserve

    @staticmethod
    async def verify_embedder_version(client: ModelserverClient, expected_version: str) -> None:
        """Verify the embedder's version matches expected SHA-256 (FR-025)."""
        ready_json = await client.get_ready()
        actual_version = ready_json.get("models", {}).get("embedder", {}).get("sha256")
        if not actual_version:
            raise TokenizerError("Embedder version not found in modelserver ready response")
        if actual_version != expected_version:
            raise TokenizerError(
                f"Embedder version mismatch: expected {expected_version}, got {actual_version}"
            )
