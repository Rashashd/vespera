"""SQLAlchemy ORM model for an authenticatable user (tenant-scoped, two roles; spec 2)."""

from datetime import datetime

from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTable
from sqlalchemy import BigInteger, DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(SQLAlchemyBaseUserTable[int], Base):
    """A person who can authenticate; carries role + client_id (data-model.md)."""

    __tablename__ = "users"

    # BigInteger PK (research D4) so the audit_log.actor_user_id FK coexists with sentinel 0.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # email / hashed_password / is_active / is_superuser / is_verified come from the base table.
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    client_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (Index("ix_users_client_id", "client_id"),)
