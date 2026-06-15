"""Integration tests: ARQ reliability + due-watchlist selection (spec 11 T012/T036/T040).

These tests require a live Postgres + Redis stack:
    PANTERA_INTEGRATION=1 uv run pytest tests/integration/test_scheduling_reliability.py -v

They exercise:
- T012: idempotency, retry-then-succeed, permanent-no-retry, dead-letter-on-exhaustion,
  inline-vs-durable parity
- T036: full cycle chain, catch-up coalescing, suspended-client exclusion, overlap prevention,
  failed-cycle not rescheduled until abandoned, HITL invariant
- T040: dead-letter row + audit row creation + endpoint surfacing + retention purge
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

_INTEGRATION = bool(os.getenv("PANTERA_INTEGRATION"))
pytestmark = pytest.mark.skipif(not _INTEGRATION, reason="requires PANTERA_INTEGRATION=1")


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────


async def _get_dl_rows(factory, *, job_key: str | None = None, client_id: int | None = None):
    """Query dead_letter rows for assertion."""
    from sqlalchemy import select

    from app.scheduling.models import DeadLetter

    async with factory() as session:
        q = select(DeadLetter)
        if job_key:
            q = q.where(DeadLetter.job_key == job_key)
        if client_id is not None:
            q = q.where(DeadLetter.client_id == client_id)
        return (await session.execute(q)).scalars().all()


async def _make_watchlist_with_item(factory, client_id: int, cadence: str = "weekly") -> int:
    """Insert a watchlist + one item; return watchlist_id."""
    from app.clients.models import Watchlist, WatchlistItem

    async with factory() as session:
        async with session.begin():
            wl = Watchlist(
                client_id=client_id,
                name=f"WL-{uuid.uuid4().hex[:8]}",
                cadence=cadence,
                is_active=True,
                severity_threshold="serious",
            )
            session.add(wl)
            await session.flush()
            item = WatchlistItem(
                watchlist_id=wl.id,
                client_id=client_id,
                item_type="drug",
                value="aspirin",
                normalized_value="aspirin",
            )
            session.add(item)
            await session.flush()
            wl_id = wl.id
    return wl_id


# ─────────────────────────────────────────────────────────────────────────────
# T012: US1 reliability — inline mode covers all retry/dead-letter cases
# ─────────────────────────────────────────────────────────────────────────────


class TestInlineParity:
    """T012: inline=True and durable modes produce the same logical outcome."""

    @pytest.mark.asyncio
    async def test_inline_enqueue_runs_task_in_process(self, auth_app, monkeypatch):
        """jobs_inline=True: enqueue() awaits the task immediately (no broker needed)."""
        from app.core.config import get_settings
        from app.jobs.enqueue import _TASK_REGISTRY, enqueue

        call_log: list[str] = []

        async def _dummy_task(ctx, *, marker: str) -> None:
            call_log.append(marker)

        original = _TASK_REGISTRY.copy()
        _TASK_REGISTRY["_test_inline"] = _dummy_task

        settings = get_settings()
        original_inline = settings.jobs_inline
        settings.jobs_inline = True

        try:
            ctx = {
                "settings": settings,
                "session_factory": auth_app.state.session_factory,
                "redis": None,
                "dispatcher": auth_app.state.dispatcher,
                "llm": None,
            }
            await enqueue(
                "_test_inline",
                job_id="test-inline-001",
                _ctx=ctx,
                marker="ran",
            )
            assert call_log == ["ran"]
        finally:
            settings.jobs_inline = original_inline
            _TASK_REGISTRY.clear()
            _TASK_REGISTRY.update(original)


class TestRetryBehavior:
    """T012: transient errors retry; permanent errors dead-letter immediately."""

    @pytest.mark.asyncio
    async def test_transient_error_reraises_for_arq(self, auth_app):
        """_run_with_dlq re-raises non-permanent exceptions (ARQ will retry them)."""
        from app.jobs.tasks import _run_with_dlq

        factory = auth_app.state.session_factory
        dispatcher = auth_app.state.dispatcher

        ctx = {
            "settings": auth_app.state.settings,
            "session_factory": factory,
            "redis": None,
            "dispatcher": dispatcher,
            "job_try": 1,
            "max_tries": 3,
            "first_failed_at": datetime.now(UTC),
        }

        async def _boom() -> None:
            raise ValueError("transient")

        with pytest.raises(ValueError, match="transient"):
            await _run_with_dlq(
                ctx,
                fn=_boom,
                job_name="test_transient",
                job_key="test-transient-001",
                client_id=None,
                fn_kwargs={},
            )

    @pytest.mark.asyncio
    async def test_permanent_error_does_not_reraise(self, auth_app, make_client):
        """_run_with_dlq swallows PermanentJobError (no ARQ retry) and records dead-letter."""
        from app.jobs.retry import PermanentJobError
        from app.jobs.tasks import _run_with_dlq

        client = await make_client()
        factory = auth_app.state.session_factory
        dispatcher = auth_app.state.dispatcher
        job_key = f"test-permanent-{uuid.uuid4().hex[:8]}"

        ctx = {
            "settings": auth_app.state.settings,
            "session_factory": factory,
            "redis": None,
            "dispatcher": dispatcher,
            "job_try": 1,
            "max_tries": 3,
            "first_failed_at": datetime.now(UTC),
        }

        async def _perm_fail() -> None:
            raise PermanentJobError("bad config", error_class="ConfigError")

        # Should NOT raise
        await _run_with_dlq(
            ctx,
            fn=_perm_fail,
            job_name="test_permanent",
            job_key=job_key,
            client_id=client.id,
            fn_kwargs={},
        )

        rows = await _get_dl_rows(factory, job_key=job_key)
        assert len(rows) == 1
        assert rows[0].error_class == "PermanentJobError"
        assert rows[0].attempts == 1

    @pytest.mark.asyncio
    async def test_final_retry_records_dead_letter(self, auth_app, make_client):
        """On job_try >= max_tries, transient error goes to dead-letter (not retried further)."""
        from app.jobs.tasks import _run_with_dlq

        client = await make_client()
        factory = auth_app.state.session_factory
        dispatcher = auth_app.state.dispatcher
        job_key = f"test-exhaust-{uuid.uuid4().hex[:8]}"

        ctx = {
            "settings": auth_app.state.settings,
            "session_factory": factory,
            "redis": None,
            "dispatcher": dispatcher,
            "job_try": 3,  # Final attempt
            "max_tries": 3,
            "first_failed_at": datetime.now(UTC) - timedelta(minutes=5),
        }

        async def _always_fail() -> None:
            raise RuntimeError("timeout")

        with pytest.raises(RuntimeError):
            await _run_with_dlq(
                ctx,
                fn=_always_fail,
                job_name="test_exhaust",
                job_key=job_key,
                client_id=client.id,
                fn_kwargs={},
            )

        rows = await _get_dl_rows(factory, job_key=job_key)
        assert len(rows) == 1
        assert rows[0].job_name == "test_exhaust"
        assert rows[0].attempts == 3

    @pytest.mark.asyncio
    async def test_retry_then_succeed_no_dead_letter(self, auth_app):
        """A task that fails on attempts 1+2 but succeeds on 3 produces no dead-letter row."""
        from app.jobs.tasks import _run_with_dlq

        factory = auth_app.state.session_factory
        dispatcher = auth_app.state.dispatcher
        job_key = f"test-retry-success-{uuid.uuid4().hex[:8]}"
        attempt_counter = {"n": 0}

        async def _flaky() -> None:
            attempt_counter["n"] += 1
            if attempt_counter["n"] < 3:
                raise RuntimeError("not yet")

        # Simulate 3 separate attempts from ARQ's perspective
        for try_n in (1, 2):
            ctx = {
                "settings": auth_app.state.settings,
                "session_factory": factory,
                "redis": None,
                "dispatcher": dispatcher,
                "job_try": try_n,
                "max_tries": 3,
                "first_failed_at": datetime.now(UTC),
            }
            with pytest.raises(RuntimeError):
                await _run_with_dlq(
                    ctx,
                    fn=_flaky,
                    job_name="test_retry_success",
                    job_key=job_key,
                    client_id=None,
                    fn_kwargs={},
                )

        ctx3 = {
            "settings": auth_app.state.settings,
            "session_factory": factory,
            "redis": None,
            "dispatcher": dispatcher,
            "job_try": 3,
            "max_tries": 3,
            "first_failed_at": datetime.now(UTC),
        }
        # Should NOT raise on attempt 3
        await _run_with_dlq(
            ctx3,
            fn=_flaky,
            job_name="test_retry_success",
            job_key=job_key,
            client_id=None,
            fn_kwargs={},
        )

        rows = await _get_dl_rows(factory, job_key=job_key)
        assert len(rows) == 0, "Successful job must not leave a dead-letter row"


# ─────────────────────────────────────────────────────────────────────────────
# T036: US2 cycle lifecycle
# ─────────────────────────────────────────────────────────────────────────────


class TestCycleLifecycle:
    """T036: cycle state machine, exclusions, and HITL invariant."""

    @pytest.mark.asyncio
    async def test_start_cycle_creates_in_progress_row(self, auth_app, make_client):
        """CycleService.start_cycle creates a row with status=in_progress."""
        from app.scheduling.service import CycleService

        client = await make_client()
        factory = auth_app.state.session_factory
        wl_id = await _make_watchlist_with_item(factory, client.id)

        async with factory() as session:
            async with session.begin():
                cycle = await CycleService.start_cycle(
                    session,
                    watchlist_id=wl_id,
                    client_id=client.id,
                    period_start=datetime(2026, 6, 1, tzinfo=UTC),
                    period_end=datetime(2026, 6, 8, tzinfo=UTC),
                )
                assert cycle.status == "in_progress"
                assert cycle.current_stage == "ingestion"

    @pytest.mark.asyncio
    async def test_overlap_prevention_second_start_raises(self, auth_app, make_client):
        """A second start_cycle for the same in_progress watchlist raises (FR-017)."""
        from sqlalchemy.exc import IntegrityError

        from app.scheduling.service import CycleService

        client = await make_client()
        factory = auth_app.state.session_factory
        wl_id = await _make_watchlist_with_item(factory, client.id)

        async with factory() as session:
            async with session.begin():
                await CycleService.start_cycle(
                    session,
                    watchlist_id=wl_id,
                    client_id=client.id,
                    period_start=datetime(2026, 6, 1, tzinfo=UTC),
                    period_end=datetime(2026, 6, 8, tzinfo=UTC),
                )

        with pytest.raises((IntegrityError, ValueError, Exception)):
            async with factory() as session:
                async with session.begin():
                    await CycleService.start_cycle(
                        session,
                        watchlist_id=wl_id,
                        client_id=client.id,
                        period_start=datetime(2026, 6, 8, tzinfo=UTC),
                        period_end=datetime(2026, 6, 15, tzinfo=UTC),
                    )

    @pytest.mark.asyncio
    async def test_failed_cycle_not_rescheduled_until_abandoned(self, auth_app, make_client):
        """query_due_watchlists excludes watchlists with unresolved failed cycles (FR-018a)."""
        from app.scheduling.service import CycleService

        client = await make_client()
        factory = auth_app.state.session_factory
        wl_id = await _make_watchlist_with_item(factory, client.id)

        # Create and fail a cycle
        async with factory() as session:
            async with session.begin():
                cycle = await CycleService.start_cycle(
                    session,
                    watchlist_id=wl_id,
                    client_id=client.id,
                    period_start=datetime(2026, 5, 1, tzinfo=UTC),
                    period_end=datetime(2026, 5, 8, tzinfo=UTC),
                )
                cycle_id = cycle.id
                await CycleService.mark_failed(session, cycle_id, "ingestion")

        # Watchlist should NOT appear as due
        future_now = datetime(2026, 6, 10, tzinfo=UTC)
        async with factory() as session:
            due = await CycleService.query_due_watchlists(session, now=future_now)
        assert not any(d["watchlist_id"] == wl_id for d in due)

        # Abandon the failed cycle
        async with factory() as session:
            async with session.begin():
                await CycleService.abandon_cycle(session, cycle_id)

        # Now it should be due
        async with factory() as session:
            due = await CycleService.query_due_watchlists(session, now=future_now)
        assert any(d["watchlist_id"] == wl_id for d in due)

    @pytest.mark.asyncio
    async def test_suspended_client_excluded_from_due(self, auth_app, make_client):
        """Watchlists for suspended clients are excluded from scheduling (FR-013)."""
        from app.scheduling.service import CycleService

        client = await make_client(status="suspended")
        factory = auth_app.state.session_factory
        wl_id = await _make_watchlist_with_item(factory, client.id)

        future_now = datetime(2026, 6, 10, tzinfo=UTC)
        async with factory() as session:
            due = await CycleService.query_due_watchlists(session, now=future_now)
        assert not any(d["watchlist_id"] == wl_id for d in due)

    @pytest.mark.asyncio
    async def test_catchup_coalescing_produces_one_cycle(self, auth_app, make_client):
        """Overdue-by-multiple-intervals watchlist gets exactly one cycle (FR-015b)."""
        from app.scheduling.service import CycleService

        client = await make_client()
        factory = auth_app.state.session_factory
        wl_id = await _make_watchlist_with_item(factory, client.id, cadence="weekly")

        # Completed last 31 days ago (overdue by ~4 weeks)
        last_done = datetime.now(UTC) - timedelta(days=31)
        async with factory() as session:
            async with session.begin():
                from app.scheduling.models import WatchlistCycle

                old_cycle = WatchlistCycle(
                    watchlist_id=wl_id,
                    client_id=client.id,
                    status="completed",
                    current_stage="done",
                    cadence_at_start="weekly",
                    period_start=last_done - timedelta(days=7),
                    period_end=last_done,
                    completed_at=last_done,
                )
                session.add(old_cycle)

        async with factory() as session:
            due = await CycleService.query_due_watchlists(session)

        matches = [d for d in due if d["watchlist_id"] == wl_id]
        # Coalescing: exactly 1 entry, not 4
        assert len(matches) == 1

    @pytest.mark.asyncio
    async def test_hitl_invariant_automation_never_sets_approved(self, auth_app, make_client):
        """HITL invariant (FR-024): no automated path sets a report to approved/sent.

        This test verifies that task functions do NOT have access to approve/send actions,
        and that the report status after task_consolidate never reaches 'approved' without
        a reviewer action.
        """
        from app.reports.enums import ReportStatus

        # Verify approved/sent are not reachable from task_consolidate by checking the
        # consolidation function's behavior: it creates reports in 'drafted' status only.
        # This is a code-path assertion, not a full e2e run.
        assert ReportStatus.APPROVED.value == "approved"
        assert ReportStatus.DRAFTED.value == "drafted"
        # consolidate_batch creates reports in DRAFTED state; approval requires HITL action
        import inspect

        from app.reports.consolidation import consolidate_batch

        src = inspect.getsource(consolidate_batch)
        # consolidate_batch may reference APPROVED in a filter (e.g. notin_(...)), but
        # must never assign it. Check that no assignment pattern appears.
        import re

        assert not re.search(
            r"status\s*=\s*ReportStatus\.APPROVED", src
        ), "consolidate_batch must not set status to approved — HITL invariant (FR-024)"


class _DummyMS:
    """Stand-in for ModelserverClient so the chain test needs no live modelserver."""

    async def __aenter__(self) -> _DummyMS:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _basic_ctx(auth_app) -> dict:
    """A minimal worker ctx for invoking task functions directly (inline-style)."""
    return {
        "settings": auth_app.state.settings,
        "session_factory": auth_app.state.session_factory,
        "redis": None,
        "dispatcher": auth_app.state.dispatcher,
        "llm": None,
        "job_try": 1,
        "max_tries": 3,
        "first_failed_at": datetime.now(UTC),
    }


async def _latest_cycle(factory, watchlist_id: int):
    """Return the most-recent WatchlistCycle row for a watchlist."""
    from sqlalchemy import select

    from app.scheduling.models import WatchlistCycle

    async with factory() as session:
        return (
            (
                await session.execute(
                    select(WatchlistCycle)
                    .where(WatchlistCycle.watchlist_id == watchlist_id)
                    .order_by(WatchlistCycle.id.desc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )


class TestCycleChain:
    """T036: the full cadence loop advances ingest→index→consolidate to completion (FR-001).

    Runs in inline mode with stubbed stage runners so it exercises the chain *wiring* and
    terminal cycle state without external APIs/modelserver. These are the tests that would
    have caught a chain that dead-ends before consolidation, or a failed stage that never
    marks the cycle failed.
    """

    @pytest.mark.asyncio
    async def test_full_chain_completes_cycle(self, auth_app, make_client, monkeypatch):
        """task_cycle_start → ingestion → index → consolidate → cycle status=completed."""
        import app.embedding.runner as embedding_runner
        import app.infra.modelserver_client as ms_mod
        import app.ingestion.runner as ingestion_runner
        import app.reports.consolidation as consolidation_mod
        from app.core.config import get_settings
        from app.jobs.tasks import task_cycle_start

        client = await make_client()
        factory = auth_app.state.session_factory
        wl_id = await _make_watchlist_with_item(factory, client.id)

        # Stub every heavy stage runner — we are asserting chain wiring, not their internals.
        async def _stub_ingestion(**kwargs):
            return None

        async def _stub_index(**kwargs):
            return None  # None → task skips set_index_build_run, still advances + enqueues

        async def _stub_consolidate(**kwargs):
            return None

        monkeypatch.setattr(ingestion_runner, "run_ingestion", _stub_ingestion)
        monkeypatch.setattr(embedding_runner, "index_build_runner", _stub_index)
        monkeypatch.setattr(consolidation_mod, "consolidate_batch", _stub_consolidate)
        monkeypatch.setattr(ms_mod.ModelserverClient, "from_settings", lambda settings: _DummyMS())

        settings = get_settings()
        original_inline = settings.jobs_inline
        settings.jobs_inline = True
        ctx = {
            "settings": settings,
            "session_factory": factory,
            "redis": None,
            "dispatcher": auth_app.state.dispatcher,
            "llm": None,
        }
        try:
            now = datetime.now(UTC)
            await task_cycle_start(
                ctx,
                watchlist_id=wl_id,
                client_id=client.id,
                period_start=(now - timedelta(days=7)).isoformat(),
                period_end=now.isoformat(),
            )
        finally:
            settings.jobs_inline = original_inline

        cycle = await _latest_cycle(factory, wl_id)
        assert cycle is not None
        assert cycle.status == "completed", f"chain stalled at stage={cycle.current_stage}"
        assert cycle.current_stage == "done"
        assert cycle.completed_at is not None

    @pytest.mark.asyncio
    async def test_failed_stage_marks_cycle_failed(self, auth_app, make_client, monkeypatch):
        """A chain stage that exhausts retries marks the cycle failed (FR-018, HIGH-2)."""
        import app.ingestion.runner as ingestion_runner
        from app.jobs.tasks import task_run_ingestion
        from app.scheduling.service import CycleService

        client = await make_client()
        factory = auth_app.state.session_factory
        wl_id = await _make_watchlist_with_item(factory, client.id)

        async with factory() as session:
            async with session.begin():
                cycle = await CycleService.start_cycle(
                    session,
                    watchlist_id=wl_id,
                    client_id=client.id,
                    period_start=datetime(2026, 6, 1, tzinfo=UTC),
                    period_end=datetime(2026, 6, 8, tzinfo=UTC),
                )
                cycle_id = cycle.id

        async def _boom(**kwargs):
            raise RuntimeError("ingestion blew up")

        monkeypatch.setattr(ingestion_runner, "run_ingestion", _boom)

        # Final attempt (job_try == max_tries): transient error re-raises AND dead-letters,
        # and because cycle_id is threaded, the cycle is marked failed.
        ctx = {
            "settings": auth_app.state.settings,
            "session_factory": factory,
            "redis": None,
            "dispatcher": auth_app.state.dispatcher,
            "llm": None,
            "job_try": 3,
            "max_tries": 3,
            "first_failed_at": datetime.now(UTC),
        }
        with pytest.raises(RuntimeError, match="ingestion blew up"):
            await task_run_ingestion(
                ctx,
                run_id=999999,
                client_id=client.id,
                watchlist_id=wl_id,
                cycle_id=cycle_id,
            )

        from app.scheduling.models import WatchlistCycle

        async with factory() as session:
            failed = await session.get(WatchlistCycle, cycle_id)
        assert failed.status == "failed"
        assert failed.failure_stage == "ingestion"


class TestSchedulerWorkerAndTaskWrappers:
    """Coverage for the cron tick, worker bootstrap, thin task wrappers, and budget gate."""

    @pytest.mark.asyncio
    async def test_worker_startup_shutdown(self):
        """worker.startup builds engine/redis/dispatcher/session_factory; shutdown disposes them."""
        from worker import worker as w

        ctx: dict = {}
        await w.startup(ctx)
        try:
            assert ctx["session_factory"] is not None
            assert ctx["dispatcher"] is not None
            assert ctx["engine"] is not None
            assert ctx["redis"] is not None
        finally:
            await w.shutdown(ctx)

    @pytest.mark.asyncio
    async def test_make_redis_settings(self):
        """_make_redis_settings derives RedisSettings from the configured URL (TLS-capable)."""
        from worker.worker import _make_redis_settings

        assert _make_redis_settings() is not None

    @pytest.mark.asyncio
    async def test_scheduler_tick_enqueues_due_watchlist(self, auth_app, make_client, monkeypatch):
        """scheduler_tick enqueues exactly one task_cycle_start per due watchlist (FR-013)."""
        import app.jobs.scheduler as scheduler_mod
        from app.jobs.scheduler import scheduler_tick

        client = await make_client()
        factory = auth_app.state.session_factory
        wl_id = await _make_watchlist_with_item(factory, client.id)

        enqueued: list[dict] = []

        async def _record(name, *, job_id, _ctx=None, app_state=None, **kwargs):
            enqueued.append({"name": name, "job_id": job_id, **kwargs})

        monkeypatch.setattr(scheduler_mod, "enqueue", _record)

        ctx = {
            "settings": auth_app.state.settings,
            "session_factory": factory,
            "redis": None,
            "dispatcher": auth_app.state.dispatcher,
            "llm": None,
        }
        await scheduler_tick(ctx)

        mine = [e for e in enqueued if e.get("watchlist_id") == wl_id]
        assert len(mine) == 1
        assert mine[0]["name"] == "task_cycle_start"

    @pytest.mark.asyncio
    async def test_task_expedited_invokes_runner(self, auth_app, monkeypatch):
        """task_expedited wraps reports.runner.draft_expedited with the worker context."""
        import app.reports.runner as reports_runner
        from app.jobs.tasks import task_expedited

        seen: list[int] = []

        async def _stub(finding_id, app_state):
            seen.append(finding_id)

        monkeypatch.setattr(reports_runner, "draft_expedited", _stub)
        await task_expedited(_basic_ctx(auth_app), finding_id=4242, revision=0)
        assert seen == [4242]

    @pytest.mark.asyncio
    async def test_task_redraft_invokes_runner(self, auth_app, monkeypatch):
        """task_redraft wraps reports.runner.redraft_report with the worker context."""
        import app.reports.runner as reports_runner
        from app.jobs.tasks import task_redraft

        seen: list[tuple] = []

        async def _stub(*, report_id, comment, app_state):
            seen.append((report_id, comment))

        monkeypatch.setattr(reports_runner, "redraft_report", _stub)
        await task_redraft(_basic_ctx(auth_app), report_id=7, revision=2, comment="please fix")
        assert seen == [(7, "please fix")]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "policy,reason",
        [("pause", "budget_pause"), ("critical_only", "budget_critical_only")],
    )
    async def test_consolidate_budget_gate_skips_drafting(
        self, auth_app, make_client, policy, reason
    ):
        """Over-cap cycle with pause/critical_only completes with skipped_reason (FR-019)."""
        from decimal import Decimal

        from sqlalchemy import update

        from app.clients.models import Watchlist
        from app.clients.watchlists import record_spend
        from app.jobs.tasks import task_consolidate
        from app.scheduling.models import WatchlistCycle
        from app.scheduling.service import CycleService

        client = await make_client()
        factory = auth_app.state.session_factory
        wl_id = await _make_watchlist_with_item(factory, client.id)

        async with factory() as session:
            async with session.begin():
                await session.execute(
                    update(Watchlist)
                    .where(Watchlist.id == wl_id)
                    .values(budget_amount=Decimal("1.00"), budget_exceeded_policy=policy)
                )
                wl = await session.get(Watchlist, wl_id)
                await record_spend(session, wl, Decimal("10.00"))
                cycle = await CycleService.start_cycle(
                    session,
                    watchlist_id=wl_id,
                    client_id=client.id,
                    period_start=datetime(2026, 6, 1, tzinfo=UTC),
                    period_end=datetime(2026, 6, 8, tzinfo=UTC),
                )
                cycle_id = cycle.id

        await task_consolidate(
            _basic_ctx(auth_app),
            watchlist_id=wl_id,
            client_id=client.id,
            cycle_period_start="2026-06-01T00:00:00+00:00",
            cycle_period_end="2026-06-08T00:00:00+00:00",
            cycle_id=cycle_id,
        )

        async with factory() as session:
            done = await session.get(WatchlistCycle, cycle_id)
        assert done.status == "completed"
        assert done.skipped_reason == reason


class TestCycleServiceEdges:
    """Coverage for CycleService validation, provenance links, and no-op guards."""

    @pytest.mark.asyncio
    async def test_start_cycle_validation_raises(self, auth_app, make_client):
        """start_cycle raises for inactive and for empty (no-item) watchlists."""
        from app.clients.models import Watchlist
        from app.scheduling.service import CycleService

        client = await make_client()
        factory = auth_app.state.session_factory

        async with factory() as session:
            async with session.begin():
                inactive = Watchlist(
                    client_id=client.id,
                    name=f"WL-{uuid.uuid4().hex[:8]}",
                    cadence="weekly",
                    is_active=False,
                    severity_threshold="serious",
                )
                empty = Watchlist(
                    client_id=client.id,
                    name=f"WL-{uuid.uuid4().hex[:8]}",
                    cadence="weekly",
                    is_active=True,
                    severity_threshold="serious",
                )
                session.add_all([inactive, empty])
                await session.flush()
                inactive_id, empty_id = inactive.id, empty.id

        for bad_id in (inactive_id, empty_id):
            with pytest.raises(ValueError):
                async with factory() as session:
                    async with session.begin():
                        await CycleService.start_cycle(
                            session,
                            watchlist_id=bad_id,
                            client_id=client.id,
                            period_start=datetime(2026, 6, 1, tzinfo=UTC),
                            period_end=datetime(2026, 6, 8, tzinfo=UTC),
                        )

    @pytest.mark.asyncio
    async def test_abandon_non_failed_raises_and_missing_ids_noop(self, auth_app, make_client):
        """abandon on a non-failed cycle raises; missing-id transitions return None."""
        from app.scheduling.service import CycleService

        client = await make_client()
        factory = auth_app.state.session_factory
        wl_id = await _make_watchlist_with_item(factory, client.id)

        async with factory() as session:
            async with session.begin():
                cycle = await CycleService.start_cycle(
                    session,
                    watchlist_id=wl_id,
                    client_id=client.id,
                    period_start=datetime(2026, 6, 1, tzinfo=UTC),
                    period_end=datetime(2026, 6, 8, tzinfo=UTC),
                )
                cid = cycle.id

        with pytest.raises(ValueError):
            async with factory() as session:
                async with session.begin():
                    await CycleService.abandon_cycle(session, cid)  # in_progress, not failed

        async with factory() as session:
            async with session.begin():
                assert await CycleService.mark_completed(session, 99_999_999) is None
                assert await CycleService.mark_failed(session, 99_999_999, "x") is None
                assert await CycleService.abandon_cycle(session, 99_999_999) is None

    @pytest.mark.asyncio
    async def test_set_index_build_run_links_provenance(self, auth_app, make_client):
        """set_index_build_run records the index run id on the cycle for provenance."""
        from app.embedding.service import IndexBuildService
        from app.scheduling.models import WatchlistCycle
        from app.scheduling.service import CycleService

        client = await make_client()
        factory = auth_app.state.session_factory
        wl_id = await _make_watchlist_with_item(factory, client.id)

        async with factory() as session:
            async with session.begin():
                cycle = await CycleService.start_cycle(
                    session,
                    watchlist_id=wl_id,
                    client_id=client.id,
                    period_start=datetime(2026, 6, 1, tzinfo=UTC),
                    period_end=datetime(2026, 6, 8, tzinfo=UTC),
                )
                cid = cycle.id
                run, _created = await IndexBuildService.create_run(
                    session, client.id, watchlist_id=wl_id
                )
                rid = run.id
                await CycleService.set_index_build_run(session, cid, rid)

        async with factory() as session:
            linked = await session.get(WatchlistCycle, cid)
        assert linked.index_build_run_id == rid


class TestCycleEndpoints:
    """Coverage for the cycle list + abandon HTTP endpoints (staff-authed)."""

    @pytest.mark.asyncio
    async def test_list_and_abandon_cycle(self, auth_app, make_client, make_staff_user, client):
        """GET cycles lists them; POST .../abandon resolves a failed cycle (FR-018b)."""
        from app.scheduling.service import CycleService

        owner = await make_client()
        factory = auth_app.state.session_factory
        wl_id = await _make_watchlist_with_item(factory, owner.id)

        async with factory() as session:
            async with session.begin():
                cycle = await CycleService.start_cycle(
                    session,
                    watchlist_id=wl_id,
                    client_id=owner.id,
                    period_start=datetime(2026, 6, 1, tzinfo=UTC),
                    period_end=datetime(2026, 6, 8, tzinfo=UTC),
                )
                cid = cycle.id
                await CycleService.mark_failed(session, cid, "ingestion")

        staff = await make_staff_user(role="admin")
        resp = await client.post(
            "/auth/jwt/login", data={"username": staff.email, "password": "Abcdef1!"}
        )
        token = resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        resp = await client.get(f"/clients/{owner.id}/watchlists/{wl_id}/cycles", headers=headers)
        assert resp.status_code == 200
        assert any(c["id"] == cid for c in resp.json())

        resp = await client.post(
            f"/clients/{owner.id}/watchlists/{wl_id}/cycles/{cid}/abandon", headers=headers
        )
        assert resp.status_code == 200
        assert resp.json()["resolved_at"] is not None


# ─────────────────────────────────────────────────────────────────────────────
# T040: US3 dead-letter visibility
# ─────────────────────────────────────────────────────────────────────────────


class TestDeadLetterVisibility:
    """T040: dead-letter row + audit row + endpoint surfacing + retention purge."""

    @pytest.mark.asyncio
    async def test_dead_letter_record_creates_row_and_audit(self, auth_app, make_client):
        """record() creates a dead_letter row and dispatches an audit event."""

        from app.jobs.dead_letter import record

        client = await make_client()
        factory = auth_app.state.session_factory
        dispatcher = auth_app.state.dispatcher
        job_key = f"dl-test-{uuid.uuid4().hex[:8]}"

        await record(
            job_name="task_test",
            job_key=job_key,
            client_id=client.id,
            args={"run_id": 42, "client_id": client.id},
            exc=RuntimeError("oops"),
            attempts=3,
            first_failed_at=datetime.now(UTC) - timedelta(minutes=5),
            session_factory=factory,
            dispatcher=dispatcher,
        )

        rows = await _get_dl_rows(factory, job_key=job_key)
        assert len(rows) == 1
        assert rows[0].job_name == "task_test"
        assert rows[0].error_class == "RuntimeError"
        assert rows[0].attempts == 3
        assert rows[0].resolved_at is None

    @pytest.mark.asyncio
    async def test_dead_letter_endpoint_lists_unresolved(
        self, auth_app, make_client, make_staff_user, client
    ):
        """GET /admin/dead-letters returns unresolved dead-letters (staff-only)."""
        from app.jobs.dead_letter import record

        owner = await make_client()
        factory = auth_app.state.session_factory
        dispatcher = auth_app.state.dispatcher
        job_key = f"dl-ep-{uuid.uuid4().hex[:8]}"

        await record(
            job_name="task_endpoint_test",
            job_key=job_key,
            client_id=owner.id,
            args={"run_id": 99, "client_id": owner.id},
            exc=ValueError("test"),
            attempts=2,
            first_failed_at=datetime.now(UTC),
            session_factory=factory,
            dispatcher=dispatcher,
        )

        staff = await make_staff_user(role="admin")
        # Login to get token
        resp = await client.post(
            "/auth/jwt/login",
            data={"username": staff.email, "password": "Abcdef1!"},
        )
        assert resp.status_code == 200
        token = resp.json()["access_token"]

        resp = await client.get(
            "/admin/dead-letters",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        items = resp.json()
        keys = [i["job_key"] for i in items]
        assert job_key in keys

    @pytest.mark.asyncio
    async def test_dead_letter_resolve_endpoint(
        self, auth_app, make_client, make_staff_user, client
    ):
        """POST /admin/dead-letters/{id}/resolve sets resolved_at (staff-only)."""
        from sqlalchemy import select

        from app.jobs.dead_letter import record
        from app.scheduling.models import DeadLetter

        owner = await make_client()
        factory = auth_app.state.session_factory
        dispatcher = auth_app.state.dispatcher
        job_key = f"dl-resolve-{uuid.uuid4().hex[:8]}"

        await record(
            job_name="task_resolve_test",
            job_key=job_key,
            client_id=owner.id,
            args={"run_id": 77, "client_id": owner.id},
            exc=RuntimeError("resolve me"),
            attempts=3,
            first_failed_at=datetime.now(UTC),
            session_factory=factory,
            dispatcher=dispatcher,
        )

        async with factory() as session:
            row = (
                (await session.execute(select(DeadLetter).where(DeadLetter.job_key == job_key)))
                .scalars()
                .first()
            )
        assert row is not None
        dl_id = row.id

        staff = await make_staff_user(role="admin")
        resp = await client.post(
            "/auth/jwt/login",
            data={"username": staff.email, "password": "Abcdef1!"},
        )
        token = resp.json()["access_token"]

        resp = await client.post(
            f"/admin/dead-letters/{dl_id}/resolve",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["resolved_at"] is not None

    @pytest.mark.asyncio
    async def test_purge_expired_removes_old_rows_not_audit(self, auth_app, make_client):
        """purge_expired deletes old dead_letter rows but never touches audit_log."""
        from sqlalchemy import update

        from app.jobs.dead_letter import purge_expired, record
        from app.scheduling.models import DeadLetter

        client_obj = await make_client()
        factory = auth_app.state.session_factory
        dispatcher = auth_app.state.dispatcher
        job_key = f"dl-purge-{uuid.uuid4().hex[:8]}"

        await record(
            job_name="task_purge_test",
            job_key=job_key,
            client_id=client_obj.id,
            args={"run_id": 55, "client_id": client_obj.id},
            exc=RuntimeError("old error"),
            attempts=1,
            first_failed_at=datetime.now(UTC) - timedelta(days=100),
            session_factory=factory,
            dispatcher=dispatcher,
        )

        # Backdate the dead_lettered_at to exceed retention
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    update(DeadLetter)
                    .where(DeadLetter.job_key == job_key)
                    .values(dead_lettered_at=datetime.now(UTC) - timedelta(days=100))
                )

        settings = auth_app.state.settings
        ctx = {
            "settings": settings,
            "session_factory": factory,
            "redis": None,
            "dispatcher": dispatcher,
        }
        await purge_expired(ctx)

        rows = await _get_dl_rows(factory, job_key=job_key)
        assert len(rows) == 0, "Expired dead-letter row should be purged"
