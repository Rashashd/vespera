"""Typed domain events raised by modules and consumed by passive handlers."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """Base domain event with audit attribution (actor_id always set; actor_type human/system)."""

    actor_id: int
    actor_type: str
    client_id: int | None = None


@dataclass(frozen=True, slots=True)
class FindingClassified(DomainEvent):
    """A finding was assigned a triage bucket (example event for later features)."""

    finding_id: int = 0
    bucket: str = ""
    confidence: float = 0.0


@dataclass(frozen=True, slots=True)
class ReportApproved(DomainEvent):
    """A reviewer approved a report (example event for later features)."""

    report_id: int = 0
    report_type: str = ""


@dataclass(frozen=True, slots=True)
class ClientErased(DomainEvent):
    """A client's data was erased (example event for later features)."""

    erased_client_id: int = 0


# --- Auth & roles events (spec 2); payloads never carry passwords or hashes (FR-009/FR-012). ---


@dataclass(frozen=True, slots=True)
class UserLoggedIn(DomainEvent):
    """A user authenticated successfully."""

    user_id: int = 0
    email: str = ""


@dataclass(frozen=True, slots=True)
class LoginFailed(DomainEvent):
    """A login attempt failed (system actor when the email is unknown)."""

    email: str = ""
    reason: str = ""


@dataclass(frozen=True, slots=True)
class UserCreated(DomainEvent):
    """An admin created a user."""

    target_user_id: int = 0
    target_email: str = ""
    role: str = ""


@dataclass(frozen=True, slots=True)
class UserRoleChanged(DomainEvent):
    """An admin changed a user's role."""

    target_user_id: int = 0
    old_role: str = ""
    new_role: str = ""


@dataclass(frozen=True, slots=True)
class UserDeactivated(DomainEvent):
    """An admin deactivated a user."""

    target_user_id: int = 0
    target_email: str = ""


# --- Client & watchlist events (spec 3); auto-audited via DomainEvent.__subclasses__ (D10). ---


@dataclass(frozen=True, slots=True)
class ClientCreated(DomainEvent):
    """A client (tenant) record was created (operator path)."""

    target_client_id: int = 0
    name: str = ""


@dataclass(frozen=True, slots=True)
class ClientUpdated(DomainEvent):
    """A client was updated (e.g. renamed); payload carries the changed fields."""

    target_client_id: int = 0
    changes: dict | None = None


@dataclass(frozen=True, slots=True)
class ClientSuspended(DomainEvent):
    """A client was suspended (operator path)."""

    target_client_id: int = 0


@dataclass(frozen=True, slots=True)
class WatchlistCreated(DomainEvent):
    """An admin created a named watchlist."""

    watchlist_id: int = 0
    name: str = ""


@dataclass(frozen=True, slots=True)
class WatchlistUpdated(DomainEvent):
    """An admin updated a watchlist's name/cadence/severity/budget; payload carries the diff."""

    watchlist_id: int = 0
    changes: dict | None = None


@dataclass(frozen=True, slots=True)
class WatchlistDeactivated(DomainEvent):
    """An admin soft-deleted (deactivated) a watchlist (FR-017)."""

    watchlist_id: int = 0


@dataclass(frozen=True, slots=True)
class WatchlistItemAdded(DomainEvent):
    """An admin added an item to a watchlist (only when a row is actually created)."""

    watchlist_id: int = 0
    item_id: int = 0
    item_type: str = ""
    value: str = ""


@dataclass(frozen=True, slots=True)
class WatchlistItemRemoved(DomainEvent):
    """An admin removed an item from a watchlist (only when a row is deleted)."""

    watchlist_id: int = 0
    item_id: int = 0


# --- Ingestion events (spec 4); auto-audited via DomainEvent.__subclasses__ (D14). ---


@dataclass(frozen=True, slots=True)
class IngestionRunTriggered(DomainEvent):
    """An admin triggered a literature ingestion run for a watchlist."""

    run_id: int = 0
    watchlist_id: int = 0
