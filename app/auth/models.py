"""SQLAlchemy ORM model for an authenticatable user (spec 4b: staff/client agency model)."""

from datetime import datetime

from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTable
from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class User(SQLAlchemyBaseUserTable[int], Base):
    """A person who can authenticate; staff have client_id=NULL, client-users have it set."""

    __tablename__ = "users"

    # BigInteger PK so the audit_log.actor_user_id FK coexists with sentinel 0 (research D4).
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # email / hashed_password / is_active / is_superuser / is_verified come from the base table.
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    # user_type distinguishes internal staff (manager/admin/reviewer) from client-side users.
    user_type: Mapped[str] = mapped_column(String(8), nullable=False, server_default="staff")
    # NULL for staff; exactly one client for client-users (ck_users_type_client enforces it).
    client_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("clients.id"), nullable=True
    )
    # Visibility mode for client-users; NULL for staff (FR-014).
    client_scope: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # Severity floor for scoped client-users; NULL means no floor filter.
    min_severity: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    watchlist_scopes: Mapped[list["UserWatchlistScope"]] = relationship(
        "UserWatchlistScope",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('manager','admin','reviewer','client_user')",
            name="ck_users_role",
        ),
        CheckConstraint(
            "(user_type='staff' AND client_id IS NULL) OR "
            "(user_type='client' AND client_id IS NOT NULL)",
            name="ck_users_type_client",
        ),
        CheckConstraint(
            "client_scope IS NULL OR client_scope IN ('full','scoped')",
            name="ck_users_client_scope",
        ),
        CheckConstraint(
            "min_severity IS NULL OR "
            "min_severity IN ('non-serious','serious','life-threatening')",
            name="ck_users_min_severity",
        ),
        Index("ix_users_client_id", "client_id"),
    )


class UserWatchlistScope(Base):
    """Junction: which watchlists a scoped client-user may see (FR-014; ON DELETE CASCADE)."""

    __tablename__ = "user_watchlist_scope"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    watchlist_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False
    )
    # Denormalized for efficient tenant queries; equals both user.client_id and watchlist.client_id.
    client_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ux_user_watchlist_scope", "user_id", "watchlist_id", unique=True),
        Index("ix_user_watchlist_scope_user_id", "user_id"),
        Index("ix_user_watchlist_scope_client_id", "client_id"),
    )
