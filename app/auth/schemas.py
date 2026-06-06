"""Pydantic schemas and the Role enum for the auth API boundary (no ORM leakage; FR-009)."""

from datetime import datetime
from enum import StrEnum

from fastapi_users import schemas
from pydantic import BaseModel, EmailStr


class Role(StrEnum):
    """The two authorization roles in Pantera (FR-004)."""

    ADMIN = "admin"
    REVIEWER = "reviewer"


class UserRead(schemas.BaseUser[int]):
    """User returned by the API; inherits id/email/active flags, never a password (FR-009)."""

    role: Role
    client_id: int
    created_at: datetime | None = None


class UserCreate(schemas.BaseUserCreate):
    """Internal create schema consumed by the UserManager (carries role + client_id)."""

    role: Role
    client_id: int


class UserUpdate(schemas.BaseUserUpdate):
    """Internal update schema consumed by the UserManager."""

    role: Role | None = None


class AdminUserCreate(BaseModel):
    """Admin-facing create request; client_id comes from the token, never the body (FR-007)."""

    email: EmailStr
    password: str
    role: Role


class AdminUserUpdate(BaseModel):
    """Admin-facing PATCH request: change role and/or active status."""

    role: Role | None = None
    is_active: bool | None = None
