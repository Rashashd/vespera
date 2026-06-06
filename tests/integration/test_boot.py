"""End-to-end boot test: the app starts and serves a healthy liveness probe (US1/SC-001)."""

import os

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires the Compose stack (Vault + Postgres + Redis) with secrets written",
)


async def test_boot_reaches_healthy_state():
    """With all dependencies healthy, lifespan completes and /health returns ok."""
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):  # runs ordered startup
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
