"""Login rate-limit integration test: 5/min/IP, 6th attempt 429 (US4, FR-010/SC-004)."""

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires the Compose stack (Vault + Postgres + Redis)",
)


async def test_login_throttled_after_five_attempts(client, make_user):
    """The 6th login attempt within the window is rejected with 429 (SC-004)."""
    from app.auth.rate_limit import login_limiter

    login_limiter.reset()  # clear any counters left by prior runs for a deterministic window
    user = await make_user(password="Abcdef1!")

    statuses = []
    for _ in range(6):
        resp = await client.post(
            "/auth/jwt/login", data={"username": user.email, "password": "Wrongpass1!"}
        )
        statuses.append(resp.status_code)

    assert statuses[:5] == [400, 400, 400, 400, 400]  # processed (bad credentials)
    assert statuses[5] == 429  # throttled


async def test_within_budget_login_succeeds(client, make_user):
    """A legitimate login within the attempt budget is not impeded (SC-004)."""
    from app.auth.rate_limit import login_limiter

    login_limiter.reset()
    user = await make_user(password="Abcdef1!")
    resp = await client.post(
        "/auth/jwt/login", data={"username": user.email, "password": "Abcdef1!"}
    )
    assert resp.status_code == 200
