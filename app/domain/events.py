"""Typed domain events raised by modules and consumed by passive handlers."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """Base domain event with audit attribution (actor_id always set; actor_type human/system)."""

    actor_id: int
    actor_type: str
    client_id: int | None = None


@dataclass(frozen=True, slots=True)
class FindingClassified(DomainEvent):
    """A finding was assigned a triage bucket and routed to the appropriate queue."""

    finding_id: int = 0
    bucket: str = ""
    confidence: float = 0.0
    resolution_path: str = ""  # "model" | "llm" | "escalated"
    routing_outcome: str = ""  # "pending_expedited" | "pending_batch" | "classified"


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


# --- Staff & client lifecycle events (spec 4b); all carry target_client_id (D11/FR-021). ---


@dataclass(frozen=True, slots=True)
class ClientReactivated(DomainEvent):
    """A suspended client was reactivated by a manager."""

    target_client_id: int = 0


@dataclass(frozen=True, slots=True)
class ClientReportEmailChanged(DomainEvent):
    """An admin updated a client's report delivery addresses."""

    target_client_id: int = 0
    changes: dict | None = None


@dataclass(frozen=True, slots=True)
class ClientUserCreated(DomainEvent):
    """An admin created a client-side user for a named client."""

    target_client_id: int = 0
    target_user_id: int = 0
    client_scope: str = ""


@dataclass(frozen=True, slots=True)
class ClientUserScopeChanged(DomainEvent):
    """An admin changed a client-user's visibility scope."""

    target_client_id: int = 0
    target_user_id: int = 0
    changes: dict | None = None


@dataclass(frozen=True, slots=True)
class WatchlistActivationChanged(DomainEvent):
    """A staff admin changed a watchlist's is_active flag (FR-027)."""

    target_client_id: int = 0
    watchlist_id: int = 0
    is_active: bool = False


# --- Ingestion events (spec 4); auto-audited via DomainEvent.__subclasses__ (D14). ---


@dataclass(frozen=True, slots=True)
class IngestionRunTriggered(DomainEvent):
    """An admin triggered a literature ingestion run for a watchlist."""

    run_id: int = 0
    watchlist_id: int = 0


# --- Embedding events (spec 6); auto-audited via DomainEvent.__subclasses__ (D14). ---


@dataclass(frozen=True, slots=True)
class IndexBuildTriggered(DomainEvent):
    """A manager/admin triggered an index build for a client's document corpus."""

    run_id: int = 0


# --- Report drafting events (spec 9); auto-audited via DomainEvent.__subclasses__ (D14). ---


@dataclass(frozen=True, slots=True)
class ReportDrafted(DomainEvent):
    """The agent produced a new draft report (expedited or batch)."""

    report_id: int = 0
    report_type: str = ""


@dataclass(frozen=True, slots=True)
class ReportEdited(DomainEvent):
    """A reviewer edited a report before approving (provenance → reviewer_attested)."""

    report_id: int = 0
    report_type: str = ""


@dataclass(frozen=True, slots=True)
class ReportRejected(DomainEvent):
    """A reviewer rejected a draft, triggering a redraft run."""

    report_id: int = 0
    report_type: str = ""
    revision_count: int = 0


@dataclass(frozen=True, slots=True)
class ReportDiscarded(DomainEvent):
    """A reviewer or the system discarded a report (terminal state)."""

    report_id: int = 0
    report_type: str = ""


@dataclass(frozen=True, slots=True)
class FindingDiscarded(DomainEvent):
    """A finding was permanently discarded from the reporting pipeline."""

    finding_id: int = 0
    kind: str = ""


@dataclass(frozen=True, slots=True)
class ReportOperatorAlert(DomainEvent):
    """The agent failed to produce a groundable draft; operator intervention needed."""

    finding_id: int = 0
    reason: str = ""


@dataclass(frozen=True, slots=True)
class BatchConsolidated(DomainEvent):
    """A batch report was consolidated for a watchlist cycle."""

    watchlist_id: int = 0
    report_id: int = 0


# --- Scheduling events (spec 11); system actor (actor_id=0, actor_type="system"). ---


@dataclass(frozen=True, slots=True)
class JobDeadLettered(DomainEvent):
    """A job exhausted retries and was dead-lettered (system actor → audit)."""

    job_name: str = ""
    job_key: str = ""
    attempts: int = 0
    error_class: str = ""


@dataclass(frozen=True, slots=True)
class WatchlistBudgetThresholdReached(DomainEvent):
    """Budget warning/exceeded threshold crossed for a watchlist (FR-019c)."""

    watchlist_id: int = 0
    state: str = ""  # "warning" | "exceeded"


# --- Security hardening events (spec 12); auto-audited via DomainEvent.__subclasses__.
# Payloads carry reason CODES only — NEVER document text or PII (asdict() is persisted). ---


@dataclass(frozen=True, slots=True)
class GuardrailRefused(DomainEvent):
    """A guardrails rail blocked a guarded LLM call or document intake (FR-005)."""

    rail: str = ""  # "injection" | "jailbreak" | "topic_scope" | "cross_client"
    call_site: str = ""  # "triage" | "agent" | "intake"
    direction: str = ""  # "input" | "output"


@dataclass(frozen=True, slots=True)
class GuardrailUnavailable(DomainEvent):
    """The guardrails sidecar was unreachable/errored → fail-safe taken (FR-006)."""

    call_site: str = ""  # "triage" | "agent" | "intake"
    fail_action: str = ""  # "escalate" | "quarantine"


@dataclass(frozen=True, slots=True)
class DocumentQuarantined(DomainEvent):
    """Intake guard blocked/could-not-run → document held out of indexing+triage (FR-006a)."""

    document_id: int = 0
    reason: str = ""  # non-PII reason code


# --- Report delivery & final-wiring events (spec 13); auto-audited via DomainEvent.__subclasses__.
# reason/error fields carry PII-free codes/summaries only (scrubbed via app/redaction). ---


@dataclass(frozen=True, slots=True)
class ReportDispatched(DomainEvent):
    """An approved report was rendered and dispatched to its configured channels (FR-002/003)."""

    report_id: int = 0
    channels: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ReportDelivered(DomainEvent):
    """All configured channels confirmed delivery for a report (FR-004)."""

    report_id: int = 0


@dataclass(frozen=True, slots=True)
class ReportDeliveryFailed(DomainEvent):
    """A channel failed after retries, or the no-callback window elapsed (FR-004a/006a)."""

    report_id: int = 0
    channel: str = ""
    reason: str = ""  # PII-free failure summary


@dataclass(frozen=True, slots=True)
class ReportDeliveryHeld(DomainEvent):
    """Delivery was held — no configured channel or the client is suspended (FR-007/007a)."""

    report_id: int = 0
    reason: str = ""  # "no_channel" | "suspended"


@dataclass(frozen=True, slots=True)
class ReportResent(DomainEvent):
    """Staff re-dispatched the unconfirmed/failed channels of a report (FR-006)."""

    report_id: int = 0
    channels: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SlaEscalated(DomainEvent):
    """An overdue expedited report was escalated one SLA tier (FR-012)."""

    report_id: int = 0
    tier: int = 0  # 1 = reviewers, 2 = manager/admin


@dataclass(frozen=True, slots=True)
class AuditExported(DomainEvent):
    """A manager/admin exported the audit log (FR-018); records scope, never row content."""

    format: str = ""  # "csv" | "json"
    scope: str = ""  # "all" | "client_watchlist"
