"""Health endpoint contract test (US3 / SC-004)."""

from httpx import ASGITransport, AsyncClient

from app.main import create_app


async def test_health_returns_bare_ok():
    """GET /health returns 200 with only a bare status (no auth, no detail)."""
    app = create_app()  # routes serve without lifespan; /health uses no app.state
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
