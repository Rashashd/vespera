"""Cycle state machine and due-watchlist query (spec 11 FR-016/FR-017/FR-018a)."""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.scheduling.models import WatchlistCycle

_log = structlog.get_logger(__name__)


class CycleService:
    """CRUD + state transitions for WatchlistCycle rows."""

    @staticmethod
    async def start_cycle(
        session: AsyncSession,
        *,
        watchlist_id: int,
        client_id: int,
        period_start: datetime,
        period_end: datetime,
    ) -> WatchlistCycle:
        """Create a new in_progress cycle; raises if one already exists (FR-017/partial-unique)."""
        from app.clients.models import Watchlist

        watchlist = await session.get(Watchlist, watchlist_id)
        if watchlist is None or not watchlist.is_active:
            raise ValueError(f"Watchlist {watchlist_id} not found or inactive")
        if not watchlist.items:
            raise ValueError(f"Watchlist {watchlist_id} has no items")

        cycle = WatchlistCycle(
            watchlist_id=watchlist_id,
            client_id=client_id,
            status="in_progress",
            current_stage="ingestion",
            cadence_at_start=watchlist.cadence,
            period_start=period_start,
            period_end=period_end,
        )
        session.add(cycle)
        await session.flush()
        _log.info(
            "cycle.started",
            cycle_id=cycle.id,
            watchlist_id=watchlist_id,
            period_start=period_start.isoformat(),
        )
        return cycle

    @staticmethod
    async def get_in_progress(session: AsyncSession, watchlist_id: int) -> WatchlistCycle | None:
        """Return the watchlist's current in_progress cycle, if any (retry-safe re-entry)."""
        return (
            (
                await session.execute(
                    select(WatchlistCycle).where(
                        WatchlistCycle.watchlist_id == watchlist_id,
                        WatchlistCycle.status == "in_progress",
                    )
                )
            )
            .scalars()
            .first()
        )

    @staticmethod
    async def advance_stage(
        session: AsyncSession, cycle_id: int, stage: str
    ) -> WatchlistCycle | None:
        """Update current_stage for an in_progress cycle (idempotent — no-op if already past)."""
        cycle = await session.get(WatchlistCycle, cycle_id)
        if cycle is None or cycle.status != "in_progress":
            return cycle
        cycle.current_stage = stage
        cycle.updated_at = datetime.now(UTC)
        await session.flush()
        return cycle

    @staticmethod
    async def set_ingestion_run(session: AsyncSession, cycle_id: int, run_id: int) -> None:
        """Link ingestion_run_id to cycle for provenance."""
        cycle = await session.get(WatchlistCycle, cycle_id)
        if cycle is not None:
            cycle.ingestion_run_id = run_id
            await session.flush()

    @staticmethod
    async def set_index_build_run(session: AsyncSession, cycle_id: int, run_id: int) -> None:
        """Link index_build_run_id to cycle for provenance."""
        cycle = await session.get(WatchlistCycle, cycle_id)
        if cycle is not None:
            cycle.index_build_run_id = run_id
            await session.flush()

    @staticmethod
    async def mark_failed(
        session: AsyncSession, cycle_id: int, failure_stage: str
    ) -> WatchlistCycle | None:
        """Mark cycle failed; excludes watchlist from auto-scheduling until abandoned (FR-018a)."""
        cycle = await session.get(WatchlistCycle, cycle_id)
        if cycle is None:
            return None
        cycle.status = "failed"
        cycle.failure_stage = failure_stage
        cycle.completed_at = datetime.now(UTC)
        cycle.updated_at = datetime.now(UTC)
        await session.flush()
        _log.warning(
            "cycle.failed",
            cycle_id=cycle_id,
            watchlist_id=cycle.watchlist_id,
            failure_stage=failure_stage,
        )
        return cycle

    @staticmethod
    async def mark_completed(
        session: AsyncSession,
        cycle_id: int,
        skipped_reason: str | None = None,
    ) -> WatchlistCycle | None:
        """Mark cycle completed (with optional skipped_reason for budget-skipped drafting)."""
        cycle = await session.get(WatchlistCycle, cycle_id)
        if cycle is None:
            return None
        cycle.status = "completed"
        cycle.current_stage = "done"
        cycle.completed_at = datetime.now(UTC)
        cycle.updated_at = datetime.now(UTC)
        if skipped_reason:
            cycle.skipped_reason = skipped_reason
        await session.flush()
        _log.info("cycle.completed", cycle_id=cycle_id, skipped_reason=skipped_reason)
        return cycle

    @staticmethod
    async def abandon_cycle(session: AsyncSession, cycle_id: int) -> WatchlistCycle | None:
        """Operator abandons a failed cycle; sets resolved_at to allow rescheduling (FR-018b)."""
        cycle = await session.get(WatchlistCycle, cycle_id)
        if cycle is None:
            return None
        if cycle.status != "failed":
            raise ValueError(f"Cycle {cycle_id} is not in failed state (status={cycle.status})")
        cycle.resolved_at = datetime.now(UTC)
        cycle.updated_at = datetime.now(UTC)
        await session.flush()
        _log.info("cycle.abandoned", cycle_id=cycle_id, watchlist_id=cycle.watchlist_id)
        return cycle

    @staticmethod
    async def query_due_watchlists(
        session: AsyncSession,
        now: datetime | None = None,
    ) -> list[dict]:
        """Return watchlists due for a new cycle.

        Due criteria (FR-013/FR-018a):
        1. Client status = active
        2. Watchlist is_active = True and has items
        3. No in_progress cycle
        4. No unresolved failed cycle (status=failed AND resolved_at IS NULL)
        5. Either no completed cycle OR time since last completed_at >= cadence interval
        """
        from app.clients.models import Client, Watchlist
        from app.scheduling.due import is_due

        if now is None:
            now = datetime.now(UTC)

        # Load active watchlists with active clients
        wl_stmt = (
            select(Watchlist)
            .join(Client, Client.id == Watchlist.client_id)
            .where(
                Client.status == "active",
                Watchlist.is_active == True,  # noqa: E712
            )
        )
        watchlists = (await session.execute(wl_stmt)).scalars().all()

        results = []
        for wl in watchlists:
            if not wl.items:
                continue

            # Check for in_progress cycle (partial-unique should prevent >1, but be safe)
            in_progress = (
                (
                    await session.execute(
                        select(WatchlistCycle).where(
                            WatchlistCycle.watchlist_id == wl.id,
                            WatchlistCycle.status == "in_progress",
                        )
                    )
                )
                .scalars()
                .first()
            )
            if in_progress:
                continue

            # Check for unresolved failed cycle (FR-018a)
            unresolved_failed = (
                (
                    await session.execute(
                        select(WatchlistCycle).where(
                            WatchlistCycle.watchlist_id == wl.id,
                            WatchlistCycle.status == "failed",
                            WatchlistCycle.resolved_at.is_(None),
                        )
                    )
                )
                .scalars()
                .first()
            )
            if unresolved_failed:
                continue

            # Get last completed cycle time
            last_completed_row = (
                await session.execute(
                    select(WatchlistCycle.completed_at)
                    .where(
                        WatchlistCycle.watchlist_id == wl.id,
                        WatchlistCycle.status == "completed",
                        WatchlistCycle.completed_at.is_not(None),
                    )
                    .order_by(WatchlistCycle.completed_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

            if not is_due(cadence=wl.cadence, last_completed_at=last_completed_row, now=now):
                continue

            results.append(
                {
                    "watchlist_id": wl.id,
                    "client_id": wl.client_id,
                    "cadence": wl.cadence,
                    "last_completed_at": last_completed_row,
                }
            )

        return results
