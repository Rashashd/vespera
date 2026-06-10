"""Shared no-torch tokenization with 512-token truncation safety net (D8/FR-005a).

Callers are responsible for chunking; truncation here is a last-resort safety net.
"""

from __future__ import annotations

import numpy as np
from tokenizers import Tokenizer

from modelserver.logging import get_logger

_log = get_logger(__name__)


def load_tokenizer(tokenizer_path: str) -> Tokenizer:
    """Load a HuggingFace fast tokenizer from a tokenizer.json file."""
    return Tokenizer.from_file(tokenizer_path)


def tokenize_batch(
    tokenizer: Tokenizer,
    texts: list[str],
    max_length: int = 512,
) -> tuple[np.ndarray, np.ndarray]:
    """Tokenize a batch of texts; truncate to max_length and warn on truncation.

    Returns (input_ids, attention_mask) as int64 numpy arrays of shape [B, S].
    Emits a structured warning with truncated_count (never the text itself — FR-020).
    """
    if not texts:
        return np.zeros((0, 0), dtype=np.int64), np.zeros((0, 0), dtype=np.int64)

    # Pre-check for over-long inputs (counts only; no text logged — D16)
    tokenizer.no_truncation()
    pre_enc = tokenizer.encode_batch(texts)
    truncated_count = sum(1 for e in pre_enc if len(e.ids) > max_length)
    if truncated_count:
        _log.warning(
            "input_truncated",
            truncated_count=truncated_count,
            max_length=max_length,
        )

    # Encode with truncation + padding
    tokenizer.enable_truncation(max_length=max_length)
    tokenizer.enable_padding()
    encodings = tokenizer.encode_batch(texts)

    input_ids = np.array([e.ids for e in encodings], dtype=np.int64)
    attention_mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
    return input_ids, attention_mask
