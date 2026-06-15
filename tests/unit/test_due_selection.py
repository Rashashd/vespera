"""Unit tests for cadence due-ness calculation (pure, no DB — spec 11 T025)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.scheduling.due import (
    cadence_interval_end,
    cadence_seconds,
    compute_period,
    is_due,
)

# ── cadence_interval_end ──────────────────────────────────────────────────────


def test_daily_interval():
    start = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    assert cadence_interval_end(start, "daily") == datetime(2026, 6, 2, 12, 0, tzinfo=UTC)


def test_weekly_interval():
    start = datetime(2026, 6, 1, tzinfo=UTC)
    assert cadence_interval_end(start, "weekly") == datetime(2026, 6, 8, tzinfo=UTC)


def test_biweekly_interval():
    start = datetime(2026, 6, 1, tzinfo=UTC)
    assert cadence_interval_end(start, "biweekly") == datetime(2026, 6, 15, tzinfo=UTC)


def test_monthly_interval_basic():
    start = datetime(2026, 1, 15, tzinfo=UTC)
    assert cadence_interval_end(start, "monthly") == datetime(2026, 2, 15, tzinfo=UTC)


def test_monthly_interval_year_boundary():
    start = datetime(2025, 12, 15, tzinfo=UTC)
    assert cadence_interval_end(start, "monthly") == datetime(2026, 1, 15, tzinfo=UTC)


def test_monthly_interval_clamps_day():
    """Jan 31 + 1 month → Feb 28 (not Feb 31 which doesn't exist)."""
    start = datetime(2026, 1, 31, tzinfo=UTC)
    result = cadence_interval_end(start, "monthly")
    assert result == datetime(2026, 2, 28, tzinfo=UTC)


def test_monthly_interval_not_30_days():
    """Monthly is NOT 30 days — it's calendar month arithmetic."""
    start = datetime(2026, 1, 31, tzinfo=UTC)
    thirty_days_later = start + timedelta(days=30)
    monthly_later = cadence_interval_end(start, "monthly")
    assert monthly_later != thirty_days_later


def test_unknown_cadence_raises():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="Unknown cadence"):
        cadence_interval_end(start, "fortnightly")


# ── is_due ────────────────────────────────────────────────────────────────────


def test_is_due_never_run():
    """Never-run watchlist is always due."""
    assert is_due(cadence="weekly", last_completed_at=None)


def test_is_due_interval_not_elapsed():
    now = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
    last = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)  # 5 days ago
    assert not is_due(cadence="weekly", last_completed_at=last, now=now)


def test_is_due_exactly_at_boundary():
    last = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)
    now = last + timedelta(days=7)  # exactly one week later
    assert is_due(cadence="weekly", last_completed_at=last, now=now)


def test_is_due_overdue_by_multiple_intervals():
    """Overdue by 3 weeks still returns True (coalescing: 1 cycle, not 3)."""
    last = datetime(2026, 5, 1, tzinfo=UTC)
    now = datetime(2026, 6, 1, tzinfo=UTC)  # 31 days later
    assert is_due(cadence="weekly", last_completed_at=last, now=now)


def test_is_due_suspended_not_checked_here():
    """is_due() is pure — suspended/inactive exclusion is in CycleService.query_due_watchlists."""
    # Just verifying the function doesn't know about suspension
    assert is_due(cadence="daily", last_completed_at=None)


# ── compute_period ────────────────────────────────────────────────────────────


def test_compute_period_first_cycle():
    """First cycle period ends at now, starts one interval back."""
    now = datetime(2026, 6, 10, tzinfo=UTC)
    start, end = compute_period(cadence="weekly", last_completed_at=None, now=now)
    assert end == now
    assert start == now - timedelta(days=7)


def test_compute_period_subsequent_cycle():
    last = datetime(2026, 6, 1, tzinfo=UTC)
    now = datetime(2026, 6, 10, tzinfo=UTC)
    start, end = compute_period(cadence="weekly", last_completed_at=last, now=now)
    assert start == last
    assert end == datetime(2026, 6, 8, tzinfo=UTC)


def test_compute_period_monthly():
    last = datetime(2026, 5, 1, tzinfo=UTC)
    now = datetime(2026, 6, 5, tzinfo=UTC)
    start, end = compute_period(cadence="monthly", last_completed_at=last, now=now)
    assert start == last
    assert end == datetime(2026, 6, 1, tzinfo=UTC)


def test_compute_period_first_cycle_default_now():
    """No explicit now → uses datetime.now(UTC); window spans one cadence interval."""
    start, end = compute_period(cadence="daily", last_completed_at=None)
    assert (end - start) == timedelta(days=1)


# ── cadence_seconds (used by compute_period for the first-cycle look-back) ─────


def test_cadence_seconds_all_cadences():
    assert cadence_seconds("daily") == 86400.0
    assert cadence_seconds("weekly") == 7 * 86400.0
    assert cadence_seconds("biweekly") == 14 * 86400.0
    assert cadence_seconds("monthly") == 30 * 86400.0


def test_cadence_seconds_unknown_raises():
    with pytest.raises(ValueError, match="Unknown cadence"):
        cadence_seconds("yearly")
