"""Unit tests for query normalization and cache-key determinism (T010 / US1)."""

from __future__ import annotations

import hashlib

import pytest

from app.rag.query_embed import cache_key, normalize_query, query_hash


def test_normalize_nfkc():
    """NFKC normalization collapses compatible characters."""
    assert normalize_query("ﬁrst") == "first"  # fi ligature


def test_normalize_strips_and_lowers():
    assert normalize_query("  HEPATOTOXICITY  ") == "hepatotoxicity"


def test_normalize_collapses_whitespace():
    assert normalize_query("drug  induced\tliver injury") == "drug induced liver injury"


def test_normalize_combined():
    assert normalize_query("  DrugX  LIVER\nFailure  ") == "drugx liver failure"


def test_query_hash_is_sha256_of_normalized():
    q = "  DrugX Liver Failure  "
    expected = hashlib.sha256(normalize_query(q).encode()).hexdigest()
    assert query_hash(q) == expected


def test_query_hash_deterministic():
    assert query_hash("hepatotoxicity") == query_hash("hepatotoxicity")
    assert query_hash("  HEPATOTOXICITY  ") == query_hash("hepatotoxicity")


def test_cache_key_format():
    sha = "a" * 64
    key = cache_key(sha, "test query")
    expected_qhash = hashlib.sha256(normalize_query("test query").encode()).hexdigest()
    assert key == f"rag:qemb:{sha}:{expected_qhash}"


def test_cache_key_version_scoped():
    """Different embedder shas produce different keys for the same query."""
    key1 = cache_key("a" * 64, "query")
    key2 = cache_key("b" * 64, "query")
    assert key1 != key2


def test_cache_key_query_scoped():
    """Different queries produce different keys for the same embedder."""
    sha = "a" * 64
    assert cache_key(sha, "query one") != cache_key(sha, "query two")


def test_cache_key_deterministic():
    """Same inputs always produce the same key."""
    sha = "abc123" + "0" * 58
    assert cache_key(sha, "test") == cache_key(sha, "test")
    assert cache_key(sha, "  TEST  ") == cache_key(sha, "test")


@pytest.mark.parametrize("blank", ["", " ", "\t", "\n"])
def test_blank_query_raises(blank):
    """RetrieveRequest validator should reject blank queries; normalize handles the rest."""
    from pydantic import ValidationError

    from app.rag.schemas import RetrieveRequest

    with pytest.raises(ValidationError):
        RetrieveRequest(query=blank)
