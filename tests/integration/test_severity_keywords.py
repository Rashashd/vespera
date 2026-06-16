"""Integration tests for the per-client severity-keyword endpoint (spec 8 FR-004)."""

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
async def test_set_severity_keywords_trims_and_dedupes(
    authed_admin_client: AsyncClient,
    make_client,
) -> None:
    """PATCH stores a cleaned, de-duplicated keyword list and GET echoes it back."""
    cl = await make_client()
    resp = await authed_admin_client.patch(
        f"/clients/{cl.id}/severity-keywords",
        json={"keywords": ["anaphylaxis", "  anaphylaxis ", "Stevens-Johnson", "death"]},
    )
    assert resp.status_code == 200
    assert resp.json()["custom_severity_keywords"] == [
        "anaphylaxis",
        "Stevens-Johnson",
        "death",
    ]

    # The roster endpoint now also surfaces the keywords.
    listing = await authed_admin_client.get("/clients")
    row = next(c for c in listing.json() if c["id"] == cl.id)
    assert row["custom_severity_keywords"] == ["anaphylaxis", "Stevens-Johnson", "death"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_set_severity_keywords_reviewer_denied(
    authed_reviewer_client: AsyncClient,
    make_client,
) -> None:
    """Reviewers cannot edit severity keywords (require_admin guard)."""
    cl = await make_client()
    resp = await authed_reviewer_client.patch(
        f"/clients/{cl.id}/severity-keywords",
        json={"keywords": ["death"]},
    )
    assert resp.status_code in (403, 404)
