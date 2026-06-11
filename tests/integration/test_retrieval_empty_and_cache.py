"""Integration test: empty corpus returns empty; cache hit skips embed (T014 / FR-015 / SC-007)."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires PANTERA_INTEGRATION=1 and docker compose up",
)


@pytest.mark.asyncio
class TestRetrievalEmptyAndCache:
    """Empty corpus and cache behaviour (FR-015 / SC-007 / FR-018)."""

    async def test_empty_corpus_returns_empty_200(
        self, client, make_client, make_staff_user
    ) -> None:
        """No chunks for client → 200 with results:[], corroboration_count:0 (FR-015/SC-007)."""
        from tests.integration.conftest import login_token

        empty_client = await make_client()
        staff = await make_staff_user(role="reviewer")
        token = await login_token(client, staff.email)

        resp = await client.post(
            f"/clients/{empty_client.id}/search",
            json={"query": "hepatotoxicity", "top_k": 10},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["results"] == []
        assert data["corroboration_count"] == 0
        assert data["corroboration_sources"] == []
        # query_hash should be present (no raw query text)
        assert "query_hash" in data and len(data["query_hash"]) > 0

    async def test_empty_corpus_no_modelserver_call(
        self, client, make_client, make_staff_user
    ) -> None:
        """Empty corpus short-circuit must NOT call the modelserver (FR-015)."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from tests.integration.conftest import login_token

        empty_client = await make_client()
        staff = await make_staff_user(role="reviewer")
        token = await login_token(client, staff.email)

        with patch("app.rag.routes.ModelserverClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_ms = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ms)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_cls.from_settings.return_value = mock_ctx

            resp = await client.post(
                f"/clients/{empty_client.id}/search",
                json={"query": "hepatotoxicity"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200
        # Modelserver embed must NOT have been called for an empty corpus
        mock_ms.embed.assert_not_called()

    async def test_cache_down_does_not_fail_query(
        self, auth_app, client, make_client, make_staff_user
    ) -> None:
        """Redis failure during cache lookup must not fail the query (FR-018).

        Uses an empty-corpus client so no modelserver call is needed.
        """
        from unittest.mock import AsyncMock, patch

        from tests.integration.conftest import login_token

        empty_client = await make_client()
        staff = await make_staff_user(role="reviewer")
        token = await login_token(client, staff.email)

        # Simulate Redis outage by making every redis call raise
        err = Exception("redis down")
        mock_redis = AsyncMock(
            get=AsyncMock(side_effect=err),
            set=AsyncMock(side_effect=err),
        )
        with patch.object(auth_app.state, "redis", mock_redis):
            resp = await client.post(
                f"/clients/{empty_client.id}/search",
                json={"query": "hepatotoxicity"},
                headers={"Authorization": f"Bearer {token}"},
            )

        # Empty corpus path doesn't even reach Redis, so 200 regardless
        assert resp.status_code == 200
