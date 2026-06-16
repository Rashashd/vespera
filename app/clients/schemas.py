"""Pydantic request/response schemas for the clients & watchlists API (no ORM leakage)."""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.auth.schemas import ClientScope
from app.clients.enums import Cadence, SeverityLevel, WatchlistItemType

if TYPE_CHECKING:  # pragma: no cover
    from app.auth.models import User
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


class ClientCreate(BaseModel):
    """Body for POST /clients; manager-only (contracts/client-lifecycle.md)."""

    name: str
    report_email_regular: str | None = None
    report_email_urgent: str | None = None
    urgent_severity_threshold: SeverityLevel | None = None

    _check_name = field_validator("name")(lambda cls, v: _clean_name(v))


class ClientOut(BaseModel):
    """Full client view returned by lifecycle and roster endpoints (spec 4b, FR-017)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    status: str
    report_email_regular: str | None
    report_email_urgent: str | None
    urgent_severity_threshold: str
    custom_severity_keywords: list[str] = Field(default_factory=list)
    created_at: datetime


class SeverityKeywordsUpdate(BaseModel):
    """PATCH body for /clients/{id}/severity-keywords; replaces the whole keyword list."""

    keywords: list[str] = Field(default_factory=list)


# --- Report email schema (spec 4b, US4) --------------------------------------


class ReportEmailUpdate(BaseModel):
    """PATCH body for /clients/{id}/report-emails; each field optional (FR-017)."""

    report_email_regular: str | None = None
    report_email_urgent: str | None = None
    urgent_severity_threshold: SeverityLevel | None = None


# --- Client-user schemas (spec 4b, US3) --------------------------------------


class ClientUserCreate(BaseModel):
    """Body for POST /clients/{client_id}/users; user_type/client_id forced in route (FR-014)."""

    email: str
    password: str
    client_scope: ClientScope
    min_severity: SeverityLevel | None = None
    watchlist_ids: list[int] = Field(default_factory=list)


class ClientUserUpdate(BaseModel):
    """PATCH body for /clients/{client_id}/users/{user_id}; immutable fields rejected."""

    client_scope: ClientScope | None = None
    min_severity: SeverityLevel | None = None
    watchlist_ids: list[int] | None = None
    is_active: bool | None = None


class ClientUserOut(BaseModel):
    """Client-user read response with derived watchlist_ids from the scope junction (FR-014)."""

    id: int
    email: str
    client_id: int
    role: str
    client_scope: str | None
    min_severity: str | None
    watchlist_ids: list[int]
    is_active: bool

    @classmethod
    def from_user(cls, user: "User") -> "ClientUserOut":
        """Assemble the response from an ORM User and its watchlist_scopes relationship."""
        return cls(
            id=user.id,
            email=user.email,
            client_id=user.client_id,
            role=user.role,
            client_scope=user.client_scope,
            min_severity=user.min_severity,
            watchlist_ids=[ws.watchlist_id for ws in user.watchlist_scopes],
            is_active=user.is_active,
        )


# --- Watchlists --------------------------------------------------------------


class WatchlistItemRead(BaseModel):
    """An item embedded in a watchlist read."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    item_type: WatchlistItemType
    value: str
    mesh_validity: str | None = None
    mesh_canonical: str | None = None


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
    budget_exceeded_policy: str = "continue"
    items: list[WatchlistItemAdd]

    _check_name = field_validator("name")(lambda cls, v: _clean_name(v))


class WatchlistUpdate(BaseModel):
    """PATCH body for a watchlist; every field optional (use model_fields_set to detect intent)."""

    name: str | None = None
    cadence: Cadence | None = None
    severity_threshold: SeverityLevel | None = None
    budget_amount: Decimal | None = Field(default=None, ge=0)
    budget_exceeded_policy: str | None = None
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
    budget_exceeded_policy: str = "continue"
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
