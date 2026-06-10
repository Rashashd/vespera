"""Integration test for index build auth and role-based access (T049, SC-013, FR-027)."""

import os

import pytest
from httpx import AsyncClient

from tests.integration.conftest import login_token

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires PANTERA_INTEGRATION=1 and docker compose up",
)


@pytest.mark.asyncio
class TestIndexBuildAuth:
    """Test that only manager/admin can trigger builds; reviewer/client-user get 403."""

    async def test_admin_can_trigger_index_build(
        self, client: AsyncClient, make_client, make_staff_user
    ) -> None:
        """Admin user can trigger an index build (SC-013, FR-027)."""
        # Create client and admin user
        test_client = await make_client()
        admin = await make_staff_user(role="admin")

        # Get token and trigger build
        token = await login_token(client, admin.email)
        resp = await client.post(
            f"/clients/{test_client.id}/index",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["status"] == "running"
        assert data["client_id"] == test_client.id

    async def test_manager_can_trigger_index_build(
        self, client: AsyncClient, make_client, make_staff_user
    ) -> None:
        """Manager user can trigger an index build."""
        test_client = await make_client()
        manager = await make_staff_user(role="manager")

        token = await login_token(client, manager.email)
        resp = await client.post(
            f"/clients/{test_client.id}/index",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 202

    async def test_reviewer_cannot_trigger_index_build(
        self, client: AsyncClient, make_client, make_staff_user
    ) -> None:
        """Reviewer user cannot trigger a build (403 Forbidden, FR-027)."""
        test_client = await make_client()
        reviewer = await make_staff_user(role="reviewer")

        token = await login_token(client, reviewer.email)
        resp = await client.post(
            f"/clients/{test_client.id}/index",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert (
            resp.status_code == 403
        ), f"Reviewer should get 403, got {resp.status_code}: {resp.text}"

    async def test_client_user_cannot_trigger_index_build(
        self, client: AsyncClient, make_client, make_user
    ) -> None:
        """Client-user cannot trigger a build (403 Forbidden, FR-027)."""
        test_client = await make_client()
        client_user = await make_user(client_id=test_client.id, user_type="client")

        token = await login_token(client, client_user.email)
        resp = await client.post(
            f"/clients/{test_client.id}/index",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert (
            resp.status_code == 403
        ), f"Client-user should get 403, got {resp.status_code}: {resp.text}"

    async def test_unauthenticated_cannot_trigger_index_build(
        self, client: AsyncClient, make_client
    ) -> None:
        """Unauthenticated request gets 401 Unauthorized."""
        test_client = await make_client()
        resp = await client.post(f"/clients/{test_client.id}/index")

        assert resp.status_code == 401

    async def test_list_index_runs_requires_auth(self, client: AsyncClient, make_client) -> None:
        """GET /index-runs requires authentication."""
        test_client = await make_client()
        resp = await client.get(f"/clients/{test_client.id}/index-runs")

        assert resp.status_code == 401
