"""Cadence interval math for due-ness calculation (pure — no I/O, fully unit-testable)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def cadence_interval_end(period_start: datetime, cadence: str) -> datetime:
    """Compute the period_end given a cadence and period_start (all UTC).

    monthly = add one calendar month (not 30 days) per spec data-model.
    """
    if cadence == "daily":
        return period_start + timedelta(days=1)
    if cadence == "weekly":
        return period_start + timedelta(days=7)
    if cadence == "biweekly":
        return period_start + timedelta(days=14)
    if cadence == "monthly":
        month = period_start.month + 1
        year = period_start.year + (month - 1) // 12
        month = ((month - 1) % 12) + 1
        # Clamp day to month boundary (e.g. Jan 31 → Feb 28)
        import calendar

        max_day = calendar.monthrange(year, month)[1]
        day = min(period_start.day, max_day)
        return period_start.replace(year=year, month=month, day=day)
    raise ValueError(f"Unknown cadence: {cadence!r}")


def cadence_seconds(cadence: str) -> float:
    """Approximate interval in seconds for due-ness comparison (monthly uses 30-day approx)."""
    if cadence == "daily":
        return 86400.0
    if cadence == "weekly":
        return 7 * 86400.0
    if cadence == "biweekly":
        return 14 * 86400.0
    if cadence == "monthly":
        return 30 * 86400.0  # approximation for sorting; exact check uses calendar math
    raise ValueError(f"Unknown cadence: {cadence!r}")


def is_due(
    *,
    cadence: str,
    last_completed_at: datetime | None,
    now: datetime | None = None,
) -> bool:
    """Return True if a watchlist's cadence interval has elapsed since last_completed_at.

    Coalescing (FR-015b): if last_completed_at is None or overdue by N intervals, still
    returns True → one cycle only (not N). The scheduler creates a single cycle per tick.
    """
    if now is None:
        now = datetime.now(UTC)
    if last_completed_at is None:
        return True  # never run → immediately due
    next_due = cadence_interval_end(last_completed_at, cadence)
    return now >= next_due


def compute_period(
    *,
    cadence: str,
    last_completed_at: datetime | None,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Compute the (period_start, period_end) for the next cycle.

    If there has been no prior cycle, period_start = now - cadence_interval (covers the
    missed window). If there has been a prior cycle, period_start = last_completed_at.
    """
    if now is None:
        now = datetime.now(UTC)
    if last_completed_at is None:
        # First cycle: window ends now, starts one interval back
        period_end = now
        period_start = now - timedelta(seconds=cadence_seconds(cadence))
    else:
        period_start = last_completed_at
        period_end = cadence_interval_end(last_completed_at, cadence)
    return period_start, period_end
