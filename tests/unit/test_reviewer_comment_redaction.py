"""Reviewer comments are redacted at rest (Cluster 3 / A6, D6): direct identifiers are removed
before the comment is persisted in reports.reviewer_comments; clinical content is preserved."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def _draft_report() -> MagicMock:
    r = MagicMock()
    r.id = 1
    r.client_id = 10
    r.status = "drafted"
    r.revision_count = 0
    r.report_type = "expedited"
    r.reviewer_comments = []
    r.updated_at = None
    return r


@pytest.mark.asyncio
async def test_reject_comment_redacted_at_rest():
    """A reject comment with an email identifier is stored redacted; the clinical term survives."""
    from app.reports import service as svc

    report = _draft_report()
    session = AsyncMock()
    session.get = AsyncMock(return_value=report)
    reviewer = MagicMock()
    reviewer.id = 42

    result = await svc.reject_report(
        report_id=1,
        client_id=10,
        reviewer=reviewer,
        comment="Contact reviewer at john.smith@example.com regarding the anaphylaxis finding.",
        redraft_cap=3,
        session=session,
        dispatcher=AsyncMock(),
        settings=SimpleNamespace(redaction_enabled=True),
    )

    stored = result.reviewer_comments[0]["comment"]
    assert "john.smith@example.com" not in stored  # direct identifier removed
    assert "<EMAIL_ADDRESS>" in stored  # ... replaced by the entity placeholder
    assert "anaphylaxis" in stored  # clinical content preserved


@pytest.mark.asyncio
async def test_redaction_kill_switch_keeps_comment_raw():
    """With redaction disabled (test-only switch), the comment is stored unchanged."""
    from app.reports import service as svc

    report = _draft_report()
    session = AsyncMock()
    session.get = AsyncMock(return_value=report)
    reviewer = MagicMock()
    reviewer.id = 7

    result = await svc.reject_report(
        report_id=1,
        client_id=10,
        reviewer=reviewer,
        comment="raw note with email a@b.com",
        redraft_cap=3,
        session=session,
        dispatcher=AsyncMock(),
        settings=SimpleNamespace(redaction_enabled=False),
    )

    assert result.reviewer_comments[0]["comment"] == "raw note with email a@b.com"
