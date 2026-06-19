"""Integration (US5): report download entitlement — own client 200, other client 404 (FR-017)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.reports.models import Report


async def _login(auth_app, email: str, password: str = "Abcdef1!") -> AsyncClient:
    c = AsyncClient(transport=ASGITransport(app=auth_app), base_url="http://test")
    resp = await c.post("/auth/jwt/login", data={"username": email, "password": password})
    resp.raise_for_status()
    c.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
    return c


async def _seed(factory, client_id, status="approved") -> int:
    async with factory() as s:
        async with s.begin():
            r = Report(
                client_id=client_id,
                report_type="batch",
                status=status,
                structured_fields=[{"text": "signal", "provenance": "drafted_grounded"}],
                draft_body="narrative",
            )
            s.add(r)
            await s.flush()
            return r.id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_download_owner_other_client_and_staff(
    auth_app, make_client, make_user, make_staff_user, priv_factory
) -> None:
    """Owning client-user → 200 HTML; another client's user → 404; staff acting-client → 200."""
    cl = await make_client()
    other = await make_client()
    rid = await _seed(priv_factory, cl.id, "approved")

    owner = await make_user(client_id=cl.id, role="reviewer")
    outsider = await make_user(client_id=other.id, role="reviewer")
    staff = await make_staff_user(role="reviewer")

    owner_c = await _login(auth_app, owner.email)
    resp = await owner_c.get(f"/clients/{cl.id}/reports/{rid}/download")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "attachment" in resp.headers.get("content-disposition", "")
    assert "narrative" in resp.text

    outsider_c = await _login(auth_app, outsider.email)
    assert (await outsider_c.get(f"/clients/{cl.id}/reports/{rid}/download")).status_code == 404

    staff_c = await _login(auth_app, staff.email)
    assert (await staff_c.get(f"/clients/{cl.id}/reports/{rid}/download")).status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_download_not_approved_is_404(
    auth_app, make_client, make_staff_user, priv_factory
) -> None:
    """A drafted (not yet approved) report is not downloadable."""
    cl = await make_client()
    rid = await _seed(priv_factory, cl.id, "drafted")
    staff = await make_staff_user(role="reviewer")
    staff_c = await _login(auth_app, staff.email)
    assert (await staff_c.get(f"/clients/{cl.id}/reports/{rid}/download")).status_code == 404
