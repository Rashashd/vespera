"""Integration test: search endpoint auth — suspended client refused, any staff allowed (T013)."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires PANTERA_INTEGRATION=1 and docker compose up",
)


@pytest.mark.asyncio
class TestRetrievalAuth:
    """Authentication and authorization contract for POST /clients/{id}/search (FR-021)."""

    async def test_suspended_client_refused(self, client, make_client, make_staff_user) -> None:
        """A suspended client → 400 CLIENT_SUSPENDED (acting_client guard behavior)."""
        from tests.integration.conftest import login_token

        suspended = await make_client(status="suspended")
        staff = await make_staff_user(role="reviewer")
        token = await login_token(client, staff.email)

        resp = await client.post(
            f"/clients/{suspended.id}/search",
            json={"query": "hepatotoxicity"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        assert "CLIENT_SUSPENDED" in resp.text

    async def test_unauthenticated_rejected(self, client, make_client) -> None:
        """No JWT → 401 (or 403 per FastAPI-Users; no auth header)."""
        active = await make_client()
        resp = await client.post(
            f"/clients/{active.id}/search",
            json={"query": "hepatotoxicity"},
        )
        assert resp.status_code in (401, 403)

    async def test_reviewer_staff_allowed(self, client, make_client, make_staff_user) -> None:
        """A reviewer (non-admin) staff member may call the search endpoint (Q4 clarification)."""
        from tests.integration.conftest import login_token

        active = await make_client()  # no chunks → empty response, no modelserver needed
        reviewer = await make_staff_user(role="reviewer")
        token = await login_token(client, reviewer.email)

        resp = await client.post(
            f"/clients/{active.id}/search",
            json={"query": "hepatotoxicity"},
            headers={"Authorization": f"Bearer {token}"},
        )
        # Empty corpus short-circuit → 200 with empty results (no modelserver call needed)
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"] == []
        assert data["corroboration_count"] == 0

    async def test_manager_staff_allowed(self, client, make_client, make_staff_user) -> None:
        """Manager staff may also call the search endpoint."""
        from tests.integration.conftest import login_token

        active = await make_client()
        manager = await make_staff_user(role="manager")
        token = await login_token(client, manager.email)

        resp = await client.post(
            f"/clients/{active.id}/search",
            json={"query": "hepatotoxicity"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

    async def test_invalid_body_rejected(self, client, make_client, make_staff_user) -> None:
        """Blank query → 422 validation error."""
        from tests.integration.conftest import login_token

        active = await make_client()
        staff = await make_staff_user(role="reviewer")
        token = await login_token(client, staff.email)

        resp = await client.post(
            f"/clients/{active.id}/search",
            json={"query": "   ", "top_k": 10},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    async def test_top_k_out_of_range_rejected(self, client, make_client, make_staff_user) -> None:
        """top_k > 50 → 422 validation error (FR-009)."""
        from tests.integration.conftest import login_token

        active = await make_client()
        staff = await make_staff_user(role="reviewer")
        token = await login_token(client, staff.email)

        resp = await client.post(
            f"/clients/{active.id}/search",
            json={"query": "hepatotoxicity", "top_k": 51},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422
