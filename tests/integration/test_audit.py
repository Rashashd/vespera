"""Audit handler test: one event yields exactly one audit_log row (US4 / SC-006)."""

from app.audit.handler import audit_log_handler
from app.audit.models import AuditLog
from app.domain.events import ReportApproved


class _FakeSession:
    """Minimal session capturing add() calls (no DB needed for handler logic)."""

    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)


async def test_one_event_one_audit_row():
    """The handler adds exactly one AuditLog with the event's attribution and target."""
    session = _FakeSession()
    event = ReportApproved(
        actor_id=5, actor_type="human", client_id=1, report_id=42, report_type="expedited"
    )
    await audit_log_handler(event, session)  # type: ignore[arg-type]

    assert len(session.added) == 1
    entry = session.added[0]
    assert isinstance(entry, AuditLog)
    assert entry.actor_id == 5
    assert entry.actor_type == "human"
    assert entry.event_type == "ReportApproved"
    assert entry.target == "report:42"
    assert entry.client_id == 1
