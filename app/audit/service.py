"""Audit-log query policy: role-scoped visibility + filtering for the staff viewer (FR-018).

Owns the change/outcome viewer's visibility policy (which event types each staff role may see)
and builds the filtered, ordered query used by both the list and export routes — extracted so
the two endpoints share one scoping definition instead of duplicating it. The routes translate
the built query into the HTTP list / CSV-JSON export responses.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, select

from app.audit.models import AuditLog
from app.audit.schemas import AUDIT_CATEGORIES
from app.auth.models import User
from app.auth.schemas import Role

# Auth/access events are noise in a *changes & outcomes* viewer — never surfaced here.
# (Login monitoring, if needed, belongs in a dedicated security view, not this one.)
_EXCLUDED_EVENT_TYPES = ("UserLoggedIn", "LoginFailed", "UserLoggedOut")

# An admin sees client/watchlist-management events AND report lifecycle/delivery outcomes;
# a manager sees everything; a reviewer is denied entirely (require_admin excludes reviewers).
_ADMIN_VISIBLE_EVENTS = (
    # Account / client / watchlist management
    "ClientCreated",
    "ClientUpdated",
    "ClientSuspended",
    "ClientReactivated",
    "ClientReportEmailChanged",
    "ClientUserCreated",
    "ClientUserScopeChanged",
    "WatchlistCreated",
    "WatchlistUpdated",
    "WatchlistItemAdded",
    "WatchlistItemRemoved",
    "WatchlistActivationChanged",
    # Report lifecycle + delivery outcomes (admins can review report activity too)
    "ReportDrafted",
    "ReportApproved",
    "ReportEdited",
    "ReportRejected",
    "ReportDiscarded",
    "ReportOperatorAlert",
    "ReportDispatched",
    "ReportDelivered",
    "ReportDeliveryFailed",
)


def is_manager(staff: User) -> bool:
    """Manager = superuser audit visibility (all events); admin = client/watchlist scope only."""
    return staff.role == Role.MANAGER.value


def build_scoped_query(
    staff: User,
    *,
    category: str | None = None,
    event_type: str | None = None,
    client_id: int | None = None,
    from_: datetime | None = None,
    to: datetime | None = None,
) -> tuple[Select, str]:
    """Build the role-scoped, filtered audit query + its scope label (FR-018).

    scope is "all" for a manager, "client_watchlist" for an admin (restricted to the
    management/outcome allowlist). `category`, when set, MUST be a known key — the routes
    validate it and return 400 before calling, so an unknown key here is a caller error.
    Newest-first by created_at, id.
    """
    q = (
        select(AuditLog)
        .where(AuditLog.event_type.notin_(_EXCLUDED_EVENT_TYPES))
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    )
    scope = "all"
    if not is_manager(staff):
        q = q.where(AuditLog.event_type.in_(_ADMIN_VISIBLE_EVENTS))
        scope = "client_watchlist"

    if category is not None:
        q = q.where(AuditLog.event_type.in_(AUDIT_CATEGORIES[category]))
    if event_type is not None:
        q = q.where(AuditLog.event_type == event_type)
    if client_id is not None:
        q = q.where(AuditLog.client_id == client_id)
    if from_ is not None:
        q = q.where(AuditLog.created_at >= from_)
    if to is not None:
        q = q.where(AuditLog.created_at <= to)
    return q, scope
