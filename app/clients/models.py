"""SQLAlchemy ORM models for tenants, watchlists, their items, and budget usage (spec 3)."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Client(Base):
    """A first-class tenant record backing the platform-wide client_id boundary (FR-001/FR-002)."""

    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    # Report delivery addresses (FR-017); single address each; sending deferred later.
    report_email_regular: Mapped[str | None] = mapped_column(String(320), nullable=True)
    report_email_urgent: Mapped[str | None] = mapped_column(String(320), nullable=True)
    urgent_severity_threshold: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="life-threatening"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("status IN ('active', 'suspended')", name="ck_clients_status"),
        CheckConstraint(
            "urgent_severity_threshold IN ('non-serious','serious','life-threatening')",
            name="ck_clients_urgent_threshold",
        ),
        # Case-insensitive platform-wide uniqueness without a citext dependency (research D6).
        Index("ux_clients_lower_name", func.lower(name), unique=True),
    )


class Watchlist(Base):
    """A named monitoring group owning its cadence, severity, and budget (FR-003/006/007/009)."""

    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("clients.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    cadence: Mapped[str] = mapped_column(String(16), nullable=False, server_default="weekly")
    severity_threshold: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="serious"
    )
    budget_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Eager-load items so reads are async-safe without explicit selectinload at each call site.
    items: Mapped[list["WatchlistItem"]] = relationship(
        "WatchlistItem",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="WatchlistItem.id",
    )

    __table_args__ = (
        CheckConstraint("cadence IN ('daily', 'weekly', 'monthly')", name="ck_watchlists_cadence"),
        CheckConstraint(
            "severity_threshold IN ('non-serious', 'serious', 'life-threatening')",
            name="ck_watchlists_severity",
        ),
        CheckConstraint("budget_amount >= 0", name="ck_watchlists_budget_nonneg"),
        Index("ix_watchlists_client_id", "client_id"),
        # Name unique per client, case-insensitive (FR-003).
        Index("ux_watchlists_client_lower_name", "client_id", func.lower(name), unique=True),
    )


class WatchlistItem(Base):
    """A drug / MeSH term / keyword monitored by a watchlist (single-table, research D2)."""

    __tablename__ = "watchlist_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    watchlist_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    item_type: Mapped[str] = mapped_column(String(16), nullable=False)
    value: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(512), nullable=False)
    # Added by migration 0004; only set for item_type='mesh' (FR-009).
    mesh_validity: Mapped[str | None] = mapped_column(String(12), nullable=True)
    mesh_canonical: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("item_type IN ('drug', 'mesh', 'keyword')", name="ck_watchlist_items_type"),
        Index("ix_watchlist_items_watchlist_id", "watchlist_id"),
        Index("ix_watchlist_items_client_id", "client_id"),
        # Idempotent membership: a duplicate add is a no-op, not a new row (FR-005).
        Index(
            "ux_watchlist_items_unique",
            "watchlist_id",
            "item_type",
            "normalized_value",
            unique=True,
        ),
    )


class WatchlistBudgetUsage(Base):
    """Per-UTC-calendar-month accumulated spend for a watchlist; state is derived, never stored."""

    __tablename__ = "watchlist_budget_usage"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    watchlist_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_watchlist_budget_usage_nonneg"),
        Index("ix_watchlist_budget_usage_watchlist_id", "watchlist_id"),
        Index("ix_watchlist_budget_usage_client_id", "client_id"),
        Index(
            "ux_watchlist_budget_usage_period",
            "watchlist_id",
            "period_start",
            unique=True,
        ),
    )
