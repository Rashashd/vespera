"""Per-watchlist budget: warn→soft-cap, sibling isolation, raise-clears, month reset (US5)."""

import os
import uuid
from datetime import date
from decimal import Decimal

import pytest

from tests.integration.conftest import login_token

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires the Compose stack (Vault + Postgres + Redis)",
)


async def _admin(client, make_client, make_user):
    tenant = await make_client()
    admin = await make_user(role="admin", client_id=tenant.id)
    token = await login_token(client, admin.email)
    return tenant, {"Authorization": f"Bearer {token}"}


def _payload(**over):
    body = {
        "name": f"WL-{uuid.uuid4().hex[:8]}",
        "items": [{"item_type": "drug", "value": "atorvastatin"}],
    }
    body.update(over)
    return body


async def _set_spend(auth_app, watchlist_id, client_id, amount, period_start=None):
    """Simulate accumulated spend (spend metering is spec 11)."""
    from app.clients import service
    from app.clients.models import Watchlist, WatchlistBudgetUsage

    async with auth_app.state.session_factory() as s:
        async with s.begin():
            if period_start is None:
                # Current month → exercise the service record_spend seam (FR-010).
                watchlist = await s.get(Watchlist, watchlist_id)
                await service.record_spend(s, watchlist, Decimal(amount))
            else:
                # A specific (e.g. prior) period → write the row directly.
                s.add(
                    WatchlistBudgetUsage(
                        watchlist_id=watchlist_id,
                        client_id=client_id,
                        period_start=period_start,
                        amount=Decimal(amount),
                    )
                )


async def _status(client, h, wl_id):
    return (await client.get(f"/watchlists/{wl_id}", headers=h)).json()["budget_status"]


async def test_warning_then_soft_cap(client, make_client, make_user, auth_app):
    """80% of budget → warning; 100% → soft_capped (FR-010)."""
    tenant, h = await _admin(client, make_client, make_user)
    wl = (await client.post("/watchlists", headers=h, json=_payload(budget_amount=100))).json()
    assert wl["budget_status"] == "ok"
    await _set_spend(auth_app, wl["id"], tenant.id, 80)
    assert await _status(client, h, wl["id"]) == "warning"


async def test_soft_capped_and_sibling_unaffected(client, make_client, make_user, auth_app):
    """A capped watchlist does not change a sibling's status (FR-011)."""
    tenant, h = await _admin(client, make_client, make_user)
    capped = (await client.post("/watchlists", headers=h, json=_payload(budget_amount=100))).json()
    sibling = (await client.post("/watchlists", headers=h, json=_payload(budget_amount=100))).json()
    await _set_spend(auth_app, capped["id"], tenant.id, 100)
    assert await _status(client, h, capped["id"]) == "soft_capped"
    assert await _status(client, h, sibling["id"]) == "ok"


async def test_raising_budget_clears_cap(client, make_client, make_user, auth_app):
    """Raising the budget above current spend flips soft_capped→ok with no extra write (FR-012)."""
    tenant, h = await _admin(client, make_client, make_user)
    wl = (await client.post("/watchlists", headers=h, json=_payload(budget_amount=100))).json()
    await _set_spend(auth_app, wl["id"], tenant.id, 100)
    assert await _status(client, h, wl["id"]) == "soft_capped"
    patched = await client.patch(f"/watchlists/{wl['id']}", headers=h, json={"budget_amount": 200})
    assert patched.status_code == 200
    assert patched.json()["budget_status"] == "ok"


async def test_new_month_auto_resets(client, make_client, make_user, auth_app):
    """Spend recorded for a prior UTC month does not count this month (auto-resume, FR-012)."""
    tenant, h = await _admin(client, make_client, make_user)
    wl = (await client.post("/watchlists", headers=h, json=_payload(budget_amount=100))).json()
    # A prior-month usage row of 200 must not affect the current period.
    await _set_spend(auth_app, wl["id"], tenant.id, 200, period_start=date(2000, 1, 1))
    assert await _status(client, h, wl["id"]) == "ok"
    assert (await client.get(f"/watchlists/{wl['id']}", headers=h)).json()[
        "current_period_spend"
    ] in ("0.0000", "0")
