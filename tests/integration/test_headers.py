"""Security-headers test: required headers present on every response (US5 / SC-007)."""

from httpx import ASGITransport, AsyncClient

from app.main import create_app


async def test_security_headers_present():
    """Every response carries the baseline security headers (FR-010)."""
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")

    assert "Strict-Transport-Security" in resp.headers
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["Referrer-Policy"] == "no-referrer"
    assert resp.headers["Content-Security-Policy"] == "default-src 'self'"
