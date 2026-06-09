"""Legacy client-scoped user-management routes — RETIRED in spec 4b.

Staff account management moved to app/auth/routes_staff.py (manager-only).
Client-user management moved to app/clients/routes_client_users.py (Phase 6).
This module is kept only to avoid import errors during the transition; it registers no routes.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/users", tags=["users"])
