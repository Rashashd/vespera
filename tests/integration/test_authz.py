"""Authorization matrix integration test: role guards allow/deny + 401 (US2)."""

import os

import pytest
import pytest_asyncio
from fastapi import Depends
from httpx import ASGITransport, AsyncClient

from tests.integration.conftest import login_token

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires the Compose stack (Vault + Postgres + Redis)",
)


@pytest_asyncio.fixture
async def authz_app():
    """App with two guarded demo endpoints to exercise the role matrix."""
    from app.auth.dependencies import require_admin, require_reviewer
    from app.auth.rate_limit import login_limiter
    from app.main import create_app

    app = create_app()

    @app.get("/_test/admin-only")
    async def _admin_only(_=Depends(require_admin)):
        return {"ok": "admin"}

    @app.get("/_test/reviewer-only")
    async def _reviewer_only(_=Depends(require_reviewer)):
        return {"ok": "reviewer"}

    async with app.router.lifespan_context(app):
        login_limiter.reset()
        yield app


@pytest_asyncio.fixture
async def authz_client(authz_app):
    transport = ASGITransport(app=authz_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_role_matrix(authz_client, make_user):
    """admin passes admin-only and is forbidden from reviewer-only, and vice versa."""
    admin = await make_user(role="admin")
    reviewer = await make_user(role="reviewer")
    admin_token = await login_token(authz_client, admin.email)
    reviewer_token = await login_token(authz_client, reviewer.email)
    ah = {"Authorization": f"Bearer {admin_token}"}
    rh = {"Authorization": f"Bearer {reviewer_token}"}

    assert (await authz_client.get("/_test/admin-only", headers=ah)).status_code == 200
    assert (await authz_client.get("/_test/admin-only", headers=rh)).status_code == 403
    assert (await authz_client.get("/_test/reviewer-only", headers=rh)).status_code == 200
    assert (await authz_client.get("/_test/reviewer-only", headers=ah)).status_code == 403


async def test_unauthenticated_is_401_before_role_check(authz_client):
    """No token yields 401 (unauthenticated), distinct from 403 (forbidden)."""
    assert (await authz_client.get("/_test/admin-only")).status_code == 401
    assert (await authz_client.get("/_test/reviewer-only")).status_code == 401
