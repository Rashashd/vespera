"""Unit tests for client-user scope validation rules (spec 4b, US3; FR-014)."""

import pytest

from app.clients.service import ScopeRequired, _validate_scope


def test_full_scope_has_no_constraints():
    """full scope accepts no severity/watchlist — caller sees all (FR-014)."""
    _validate_scope("full", min_severity=None, watchlist_ids=[])  # must not raise


def test_scoped_without_constraints_raises():
    """scoped with neither min_severity nor watchlist_ids is default-deny → ScopeRequired."""
    with pytest.raises(ScopeRequired):
        _validate_scope("scoped", min_severity=None, watchlist_ids=[])


def test_scoped_with_severity_is_ok():
    """scoped + min_severity is valid (severity-floor filter, all watchlists)."""
    _validate_scope("scoped", min_severity="serious", watchlist_ids=[])  # must not raise


def test_scoped_with_watchlist_is_ok():
    """scoped + watchlist_ids is valid (watchlist filter, any severity)."""
    _validate_scope("scoped", min_severity=None, watchlist_ids=[1, 2])  # must not raise


def test_scoped_with_both_is_ok():
    """scoped + severity + watchlists is valid (combined filter)."""
    _validate_scope("scoped", min_severity="life-threatening", watchlist_ids=[3])


def test_full_scope_ignores_severity():
    """full scope with min_severity set is still valid (severity is ignored for full)."""
    _validate_scope("full", min_severity="serious", watchlist_ids=[1])


def test_scoped_empty_watchlist_list_same_as_none():
    """Empty list [] is treated as no watchlist constraint — still needs min_severity."""
    with pytest.raises(ScopeRequired):
        _validate_scope("scoped", min_severity=None, watchlist_ids=[])
