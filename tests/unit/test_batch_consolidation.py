"""Unit tests for batch consolidation: grouping, idempotency, drop/discard semantics."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.reports.consolidation import (
    _build_batch_draft_body,
    _build_batch_structured_fields,
    _count_unique_documents,
)
from app.reports.enums import ReportStatus, ReportType


def _make_finding(
    id: int = 1,
    drug: str = "Warfarin",
    reaction: str = "bleeding",
    bucket: str = "minor",  # batches only ever contain minor/positive findings
    document_id: int = 100,
    client_id: int = 10,
    status: str = "pending_batch",
) -> MagicMock:
    f = MagicMock()
    f.id = id
    f.drug = drug
    f.reaction = reaction
    f.bucket = bucket
    f.document_id = document_id
    f.client_id = client_id
    f.status = status
    return f


def _make_report(
    id: int = 1,
    status: str = "drafted",
    report_type: str = "batch",
    watchlist_id: int = 5,
) -> MagicMock:
    r = MagicMock()
    r.id = id
    r.status = status
    r.report_type = report_type
    r.watchlist_id = watchlist_id
    return r


class TestBuildBatchStructuredFields:
    def test_groups_by_reaction(self):
        findings = [
            _make_finding(id=1, drug="Aspirin", reaction="bleeding"),
            _make_finding(id=2, drug="Warfarin", reaction="bleeding"),
            _make_finding(id=3, drug="Aspirin", reaction="rash"),
        ]
        claims = _build_batch_structured_fields(findings)
        assert len(claims) == 2
        reactions = {c["field"] for c in claims}
        assert reactions == {"Reaction"}
        bleeding_claim = next(c for c in claims if "bleeding" in c["text"])
        assert "Aspirin" in bleeding_claim["text"]
        assert "Warfarin" in bleeding_claim["text"]
        assert "2 findings" in bleeding_claim["text"]

    def test_provenance_is_aggregated(self):
        findings = [_make_finding()]
        claims = _build_batch_structured_fields(findings)
        # Batch summary lines aggregate already-grounded findings (not passage-grounded).
        assert all(c["provenance"] == "aggregated" for c in claims)

    def test_drugs_sorted_alphabetically(self):
        findings = [
            _make_finding(id=1, drug="Warfarin", reaction="stroke"),
            _make_finding(id=2, drug="Aspirin", reaction="stroke"),
        ]
        claims = _build_batch_structured_fields(findings)
        assert len(claims) == 1
        text = claims[0]["text"]
        assert text.index("Aspirin") < text.index("Warfarin")

    def test_single_finding_produces_one_claim(self):
        findings = [_make_finding()]
        claims = _build_batch_structured_fields(findings)
        assert len(claims) == 1


class TestCountUniqueDocuments:
    def test_counts_distinct_document_ids(self):
        findings = [
            _make_finding(id=1, document_id=100),
            _make_finding(id=2, document_id=100),
            _make_finding(id=3, document_id=200),
        ]
        assert _count_unique_documents(findings) == 2

    def test_empty_list_returns_zero(self):
        assert _count_unique_documents([]) == 0

    def test_all_same_document_returns_one(self):
        findings = [_make_finding(document_id=99) for _ in range(5)]
        assert _count_unique_documents(findings) == 1


class TestBuildBatchDraftBody:
    def test_contains_watchlist_id(self):
        findings = [_make_finding(bucket="urgent")]
        cycle_start = datetime(2025, 1, 1, tzinfo=UTC)
        body = _build_batch_draft_body(findings, watchlist_id=7, cycle_start=cycle_start)
        assert "watchlist 7" in body

    def test_contains_cycle_date(self):
        findings = [_make_finding()]
        cycle_start = datetime(2025, 6, 15, tzinfo=UTC)
        body = _build_batch_draft_body(findings, watchlist_id=1, cycle_start=cycle_start)
        assert "2025-06-15" in body

    def test_contains_finding_and_document_count(self):
        findings = [
            _make_finding(id=1, document_id=10),
            _make_finding(id=2, document_id=20),
        ]
        cycle_start = datetime(2025, 1, 1, tzinfo=UTC)
        body = _build_batch_draft_body(findings, watchlist_id=1, cycle_start=cycle_start)
        assert "2 findings" in body
        assert "2 documents" in body


class TestConsolidateBatch:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_documents(self):
        from app.reports.consolidation import consolidate_batch

        session = AsyncMock()
        # No existing report
        session.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=lambda: None),  # existing check
                MagicMock(scalars=lambda: MagicMock(all=lambda: [])),  # doc_ids
            ]
        )
        result = await consolidate_batch(
            watchlist_id=5,
            client_id=10,
            cycle_period_start=datetime(2025, 1, 1, tzinfo=UTC),
            cycle_period_end=datetime(2025, 1, 31, tzinfo=UTC),
            session=session,
            dispatcher=AsyncMock(),
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_pending_findings(self):
        from app.reports.consolidation import consolidate_batch

        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=lambda: None),  # existing check
                MagicMock(scalars=lambda: MagicMock(all=lambda: [101, 102])),  # doc_ids
                MagicMock(scalars=lambda: MagicMock(all=lambda: [])),  # no findings
            ]
        )
        result = await consolidate_batch(
            watchlist_id=5,
            client_id=10,
            cycle_period_start=datetime(2025, 1, 1, tzinfo=UTC),
            cycle_period_end=datetime(2025, 1, 31, tzinfo=UTC),
            session=session,
            dispatcher=AsyncMock(),
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_idempotent_returns_existing_active_report(self):
        from app.reports.consolidation import consolidate_batch

        existing = _make_report(id=42, status="drafted")
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: existing))
        result = await consolidate_batch(
            watchlist_id=5,
            client_id=10,
            cycle_period_start=datetime(2025, 1, 1, tzinfo=UTC),
            cycle_period_end=datetime(2025, 1, 31, tzinfo=UTC),
            session=session,
            dispatcher=AsyncMock(),
        )
        assert result is existing

    @pytest.mark.asyncio
    async def test_creates_report_and_dispatches_events(self):
        from app.domain.events import BatchConsolidated, ReportDrafted
        from app.reports.consolidation import consolidate_batch

        finding = _make_finding(id=1, document_id=100)
        dispatcher = AsyncMock()
        dispatcher.dispatch = AsyncMock()

        added_objects = []
        session = AsyncMock()
        session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
        session.flush = AsyncMock()

        call_count = 0

        def make_execute_result(call_idx):
            if call_idx == 0:
                m = MagicMock()
                m.scalar_one_or_none = lambda: None
                return m
            elif call_idx == 1:
                m = MagicMock()
                m.scalars = lambda: MagicMock(all=lambda: [100])
                return m
            else:
                m = MagicMock()
                m.scalars = lambda: MagicMock(all=lambda: [finding])
                return m

        async def execute_side_effect(*args, **kwargs):
            nonlocal call_count
            result = make_execute_result(call_count)
            call_count += 1
            return result

        session.execute = execute_side_effect

        # Give the Report a fake ID after flush
        def set_report_id():
            for obj in added_objects:
                from app.reports.models import Report

                if isinstance(obj, Report):
                    obj.id = 99

        session.flush = AsyncMock(side_effect=lambda: set_report_id())

        result = await consolidate_batch(
            watchlist_id=5,
            client_id=10,
            cycle_period_start=datetime(2025, 1, 1, tzinfo=UTC),
            cycle_period_end=datetime(2025, 1, 31, tzinfo=UTC),
            session=session,
            dispatcher=dispatcher,
        )

        assert result is not None
        assert result.report_type == ReportType.BATCH
        assert result.status == ReportStatus.DRAFTED
        # Two events dispatched
        assert dispatcher.dispatch.call_count == 2
        event_types = {type(c.args[0]) for c in dispatcher.dispatch.call_args_list}
        assert ReportDrafted in event_types
        assert BatchConsolidated in event_types
        # Finding status flipped
        assert finding.status.value == "reported" or str(finding.status) in (
            "reported",
            "FindingStatus.REPORTED",
        )
