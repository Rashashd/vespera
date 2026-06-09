"""Integration tests: incremental watermark advance + first-run lookback (T048, US5)."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires the Compose stack (Vault + Postgres + Redis)",
)

from app.ingestion.adapters import RawRecord  # noqa: E402
from app.ingestion.enums import SourceName, SourceReliability  # noqa: E402

# ---------------------------------------------------------------------------
# T048: Incremental watermark advance — second run only fetches newer records
# ---------------------------------------------------------------------------


async def test_watermark_advances_after_successful_run(auth_app, make_client):
    """After a successful run the watermark is advanced; a second run passes it as `since`."""
    from app.auth.backend import password_helper
    from app.auth.models import User
    from app.clients.models import Watchlist
    from app.ingestion.runner import run_ingestion
    from app.ingestion.service import create_run, get_watermark

    factory = auth_app.state.session_factory

    c = await make_client()

    async with factory() as s:
        async with s.begin():
            wl = Watchlist(
                client_id=c.id,
                name="watermark-wl",
                cadence="weekly",
                severity_threshold="serious",
            )
            s.add(wl)
        await s.refresh(wl)

    async with factory() as s:
        async with s.begin():
            u = User(
                email=f"wm-admin-{c.id}@test.com",
                hashed_password=password_helper.hash("Abcdef1!"),
                role="admin",
                user_type="client",
                client_id=c.id,
                is_active=True,
                is_superuser=False,
                is_verified=True,
            )
            s.add(u)
        await s.refresh(u)

    pub_date = datetime(2026, 1, 15, tzinfo=UTC)
    record = RawRecord(
        source=SourceName.PUBMED,
        source_external_id="PM-WM-001",
        raw_payload={"pmid": "PM-WM-001"},
        title="Watermark test record",
        published_at=pub_date,
    )

    calls: list[datetime | None] = []

    async def fake_fetch(query, since, cap):
        calls.append(since)
        return [record] if since is None or since <= pub_date else []

    adapter = AsyncMock()
    adapter.name = SourceName.PUBMED
    adapter.reliability = SourceReliability.PEER_REVIEWED
    adapter.fetch = AsyncMock(side_effect=fake_fetch)

    class _FakeItem:
        item_type = "drug"
        value = "aspirin"
        mesh_validity = None

    async with factory() as s:
        async with s.begin():
            run1 = await create_run(
                s, client_id=c.id, watchlist_id=wl.id, triggered_by_user_id=u.id
            )

    await run_ingestion(
        run_id=run1.id,
        client_id=c.id,
        watchlist_id=wl.id,
        watchlist_items=[_FakeItem()],
        session_factory=factory,
        adapters=[adapter],
        initial_lookback_days=365,
    )

    async with factory() as s:
        wm = await get_watermark(s, wl.id, SourceName.PUBMED)

    assert wm is not None
    assert wm.watermark_at is not None

    first_call_since = calls[0]
    assert first_call_since is not None

    async with factory() as s:
        async with s.begin():
            run2 = await create_run(
                s, client_id=c.id, watchlist_id=wl.id, triggered_by_user_id=u.id
            )

    await run_ingestion(
        run_id=run2.id,
        client_id=c.id,
        watchlist_id=wl.id,
        watchlist_items=[_FakeItem()],
        session_factory=factory,
        adapters=[adapter],
        initial_lookback_days=365,
    )

    second_call_since = calls[1]
    assert second_call_since is not None
    assert second_call_since >= first_call_since


async def test_first_run_uses_lookback_window(auth_app, make_client):
    """Without a watermark the runner passes `now - initial_lookback_days` as `since` (SC-010)."""
    from app.auth.backend import password_helper
    from app.auth.models import User
    from app.clients.models import Watchlist
    from app.ingestion.runner import run_ingestion
    from app.ingestion.service import create_run

    factory = auth_app.state.session_factory

    c = await make_client()

    async with factory() as s:
        async with s.begin():
            wl = Watchlist(
                client_id=c.id,
                name="lookback-wl",
                cadence="weekly",
                severity_threshold="serious",
            )
            s.add(wl)
        await s.refresh(wl)

    async with factory() as s:
        async with s.begin():
            u = User(
                email=f"lb-admin-{c.id}@test.com",
                hashed_password=password_helper.hash("Abcdef1!"),
                role="admin",
                user_type="client",
                client_id=c.id,
                is_active=True,
                is_superuser=False,
                is_verified=True,
            )
            s.add(u)
        await s.refresh(u)

    async with factory() as s:
        async with s.begin():
            run = await create_run(s, client_id=c.id, watchlist_id=wl.id, triggered_by_user_id=u.id)

    received_since: list[datetime | None] = []

    async def capture_fetch(query, since, cap):
        received_since.append(since)
        return []

    adapter = AsyncMock()
    adapter.name = SourceName.PUBMED
    adapter.reliability = SourceReliability.PEER_REVIEWED
    adapter.fetch = AsyncMock(side_effect=capture_fetch)

    class _FakeItem:
        item_type = "drug"
        value = "anything"
        mesh_validity = None

    lookback_days = 180
    before_run = datetime.now(UTC)
    await run_ingestion(
        run_id=run.id,
        client_id=c.id,
        watchlist_id=wl.id,
        watchlist_items=[_FakeItem()],
        session_factory=factory,
        adapters=[adapter],
        initial_lookback_days=lookback_days,
    )
    after_run = datetime.now(UTC)

    since = received_since[0]
    assert since is not None
    expected_min = before_run - timedelta(days=lookback_days)
    expected_max = after_run - timedelta(days=lookback_days)
    assert expected_min <= since <= expected_max
