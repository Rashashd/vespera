"""StrEnums mirroring the small CHECK-constrained columns of the clients/watchlists schema."""

from enum import StrEnum


class ClientStatus(StrEnum):
    """Lifecycle state of a tenant (FR-002); operator-controlled, never via the API."""

    ACTIVE = "active"
    SUSPENDED = "suspended"


class Cadence(StrEnum):
    """How often a watchlist is monitored (FR-006); default is weekly."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class SeverityLevel(StrEnum):
    """ICH-aligned severity threshold (FR-007), ordered low→high; default serious."""

    NON_SERIOUS = "non-serious"
    SERIOUS = "serious"
    LIFE_THREATENING = "life-threatening"

    @property
    def rank(self) -> int:
        """Numeric order for "minimum level that escalates" comparisons (reused by spec 8)."""
        return _SEVERITY_ORDER[self]


_SEVERITY_ORDER = {
    SeverityLevel.NON_SERIOUS: 0,
    SeverityLevel.SERIOUS: 1,
    SeverityLevel.LIFE_THREATENING: 2,
}


class WatchlistItemType(StrEnum):
    """Kind of monitored member stored in a single watchlist_items table (research D2)."""

    DRUG = "drug"
    MESH = "mesh"
    KEYWORD = "keyword"
