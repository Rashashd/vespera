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
