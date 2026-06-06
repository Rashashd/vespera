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
