"""Pydantic schemas and the Role enum for the auth API boundary (no ORM leakage; FR-009)."""

from datetime import datetime
from enum import StrEnum

from fastapi_users import schemas
from pydantic import BaseModel, EmailStr


class UserType(StrEnum):
    """Whether the account is an internal staff member or a client-side user (FR-001)."""

    STAFF = "staff"
    CLIENT = "client"


class ClientScope(StrEnum):
    """Visibility mode for client-side users; NULL for staff (FR-014)."""

    FULL = "full"
    SCOPED = "scoped"


class Role(StrEnum):
    """Authorization role in Pantera; staff roles are manager/admin/reviewer (FR-002)."""

    MANAGER = "manager"
    ADMIN = "admin"
    REVIEWER = "reviewer"
    CLIENT_USER = "client_user"


class UserRead(schemas.BaseUser[int]):
    """User returned by the API; inherits id/email/active flags, never a password (FR-009)."""

    role: Role
    user_type: UserType
    client_id: int | None = None
    created_at: datetime | None = None


class UserCreate(schemas.BaseUserCreate):
    """Internal create schema consumed by the UserManager (carries role + optional client_id)."""

    role: Role
    user_type: UserType = UserType.STAFF
    client_id: int | None = None


class UserUpdate(schemas.BaseUserUpdate):
    """Internal update schema consumed by the UserManager."""

    role: Role | None = None


class AdminUserCreate(BaseModel):
    """Legacy admin-facing create request (spec 2); superseded by StaffUserCreate for staff."""

    email: EmailStr
    password: str
    role: Role


class AdminUserUpdate(BaseModel):
    """Admin-facing PATCH request: change role and/or active status."""

    role: Role | None = None
    is_active: bool | None = None


# --- Staff account schemas (manager-only; contracts/staff-accounts.md) ---


class StaffUserCreate(BaseModel):
    """Manager-facing create request for a staff user; user_type/client_id never in body."""

    email: EmailStr
    password: str
    role: Role


class StaffUserUpdate(BaseModel):
    """Manager-facing PATCH request for a staff user."""

    role: Role | None = None
    is_active: bool | None = None


class StaffUserOut(BaseModel):
    """Staff user read response; client_id always null."""

    model_config = {"from_attributes": True}

    id: int
    email: str
    role: Role
    user_type: UserType
    is_active: bool
    created_at: datetime | None = None
