"""Unit tests for the shared safe_int coercion helper (C5)."""

from __future__ import annotations

from app.core.coercion import safe_int


def test_int_passthrough():
    assert safe_int(5) == 5


def test_numeric_string():
    assert safe_int("42") == 42


def test_none_returns_none():
    assert safe_int(None) is None


def test_malformed_string_returns_none():
    assert safe_int("abc") is None
    assert safe_int("") is None


def test_non_numeric_types_return_none():
    assert safe_int([1]) is None
    assert safe_int({}) is None


def test_float_truncates_like_int():
    # Matches the prior inline int() behavior (truncation toward zero).
    assert safe_int(3.9) == 3
