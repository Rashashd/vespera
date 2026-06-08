"""Pydantic request/response schemas for the clients & watchlists API (no ORM leakage)."""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.clients.enums import Cadence, SeverityLevel, WatchlistItemType

if TYPE_CHECKING:  # pragma: no cover
    from app.clients.models import Watchlist


def _clean_name(value: str) -> str:
    """Trim a name and reject it if empty (FR-001/FR-003)."""
    value = value.strip()
    if not value:
        raise ValueError("name must not be empty")
    return value


# --- Clients -----------------------------------------------------------------


class ClientRead(BaseModel):
    """A tenant record as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    status: str
    created_at: datetime
    updated_at: datetime


class ClientUpdate(BaseModel):
    """PATCH body for the caller's own client; `status` is operator-only, never settable here."""

    name: str | None = None

    _check_name = field_validator("name")(lambda cls, v: _clean_name(v) if v is not None else v)


# --- Watchlists --------------------------------------------------------------


class WatchlistItemRead(BaseModel):
    """An item embedded in a watchlist read."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    item_type: WatchlistItemType
    value: str


class WatchlistItemAdd(BaseModel):
    """Request body to add (or seed) a single watchlist item."""

    item_type: WatchlistItemType
    value: str

    @field_validator("value")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("value must not be empty")
        return v


class WatchlistCreate(BaseModel):
    """Request body to create a named watchlist with ≥1 item."""

    name: str
    cadence: Cadence = Cadence.WEEKLY
    severity_threshold: SeverityLevel = SeverityLevel.SERIOUS
    budget_amount: Decimal | None = Field(default=None, ge=0)
    items: list[WatchlistItemAdd]

    _check_name = field_validator("name")(lambda cls, v: _clean_name(v))


class WatchlistUpdate(BaseModel):
    """PATCH body for a watchlist; every field optional (use model_fields_set to detect intent)."""

    name: str | None = None
    cadence: Cadence | None = None
    severity_threshold: SeverityLevel | None = None
    budget_amount: Decimal | None = Field(default=None, ge=0)
    is_active: bool | None = None

    _check_name = field_validator("name")(lambda cls, v: _clean_name(v) if v is not None else v)


class WatchlistRead(BaseModel):
    """A watchlist with its items and derived budget status (data-model.md)."""

    id: int
    client_id: int
    name: str
    cadence: Cadence
    severity_threshold: SeverityLevel
    budget_amount: Decimal | None
    is_active: bool
    budget_status: str
    current_period_spend: Decimal
    items: list[WatchlistItemRead]
    created_at: datetime

    @field_serializer("budget_amount")
    def _ser_budget(self, value: Decimal | None) -> str | None:
        """Emit money at the column's 4-dp scale regardless of source (DB read vs create echo)."""
        return None if value is None else f"{value:.4f}"

    @field_serializer("current_period_spend")
    def _ser_spend(self, value: Decimal) -> str:
        """Emit spend at the same fixed 4-dp scale as budget_amount."""
        return f"{value:.4f}"

    @classmethod
    def from_watchlist(
        cls, watchlist: "Watchlist", *, budget_status: str, spend: Decimal
    ) -> "WatchlistRead":
        """Assemble the read model from an ORM watchlist plus its derived budget figures."""
        return cls(
            id=watchlist.id,
            client_id=watchlist.client_id,
            name=watchlist.name,
            cadence=Cadence(watchlist.cadence),
            severity_threshold=SeverityLevel(watchlist.severity_threshold),
            budget_amount=watchlist.budget_amount,
            is_active=watchlist.is_active,
            budget_status=budget_status,
            current_period_spend=spend,
            items=[WatchlistItemRead.model_validate(i) for i in watchlist.items],
            created_at=watchlist.created_at,
        )
