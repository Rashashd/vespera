"""Unit tests for 512-token truncation and no-truncation path (T040).

Verifies: over-long input is truncated to max_length; normal input untouched;
truncated_count warning fires (count only — no text logged per FR-020).
"""

from __future__ import annotations

import pytest

from modelserver.inference.tokenize import load_tokenizer, tokenize_batch

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fixture_tokenizer(modelserver_model_dir):
    """Load the session-scoped fixture tokenizer."""
    return load_tokenizer(str(modelserver_model_dir / "tokenizer.json"))


# ---------------------------------------------------------------------------
# Truncation behaviour
# ---------------------------------------------------------------------------


def test_short_input_not_truncated(fixture_tokenizer):
    texts = ["patient liver damage"]
    ids, mask = tokenize_batch(fixture_tokenizer, texts, max_length=512)
    assert ids.shape[0] == 1
    assert ids.shape[1] <= 512


def test_over_long_input_truncated_to_max_length(fixture_tokenizer):
    # Build a text guaranteed to exceed 512 tokens with this tokenizer
    # (WordLevel splits on whitespace; each word → 1 token)
    long_text = " ".join(["patient"] * 600)
    ids, mask = tokenize_batch(fixture_tokenizer, [long_text], max_length=512)
    assert ids.shape[1] <= 512, f"truncation did not cap to 512: shape {ids.shape}"


def test_truncation_warning_fires(fixture_tokenizer, capsys):
    long_text = " ".join(["adverse"] * 600)
    tokenize_batch(fixture_tokenizer, [long_text], max_length=512)
    out = capsys.readouterr().out
    assert "input_truncated" in out, f"Expected input_truncated in stdout; got: {out!r}"


def test_truncation_warning_count_only(fixture_tokenizer, capsys):
    """Warning must bind truncated_count — never the text content (FR-020)."""
    long_text = " ".join(["severe"] * 600)
    tokenize_batch(fixture_tokenizer, [long_text], max_length=512)
    out = capsys.readouterr().out
    assert long_text not in out, "Text content must not appear in logs"


def test_mixed_batch_truncates_only_overlong(fixture_tokenizer):
    short = "no adverse events"
    long = " ".join(["drug"] * 600)
    ids, mask = tokenize_batch(fixture_tokenizer, [short, long], max_length=512)
    assert ids.shape[0] == 2
    assert ids.shape[1] <= 512


def test_empty_batch_returns_empty(fixture_tokenizer):
    ids, mask = tokenize_batch(fixture_tokenizer, [], max_length=512)
    assert ids.shape == (0, 0)
    assert mask.shape == (0, 0)


def test_attention_mask_shape_matches_input_ids(fixture_tokenizer):
    texts = ["patient developed liver failure", "no adverse events"]
    ids, mask = tokenize_batch(fixture_tokenizer, texts)
    assert ids.shape == mask.shape
