"""Contract tests: GET /clients/{id}/findings/{finding_id} (FR-013)."""

import os

import pytest
import pytest_asyncio

from tests.integration.conftest import login_token

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"), reason="integration tests require PANTERA_INTEGRATION=1"
)


@pytest_asyncio.fixture
async def seeded_finding(auth_app, make_client, make_document):
    """Insert one finding row for a client and clean up afterward."""
    from app.triage.models import Finding

    factory = auth_app.state.session_factory
    client = await make_client()
    doc = await make_document(client_id=client.id)

    async with factory() as s:
        async with s.begin():
            finding = Finding(
                client_id=client.id,
                document_id=doc.id,
                drug="ibuprofen",
                reaction="gastrointestinal bleeding",
                bucket="urgent",
                status="pending_expedited",
                model_confidence=None,
                resolution_path="escalated",
            )
            s.add(finding)
        await s.refresh(finding)

    yield client, finding

    # CASCADE on client_id handles finding deletion when make_client teardown runs.


@pytest.mark.asyncio
async def test_get_finding_200(client, make_staff_user, seeded_finding):
    """200 with correct shape for an owned finding (FR-013)."""
    target_client, finding = seeded_finding
    staff = await make_staff_user(role="reviewer")
    token = await login_token(client, staff.email)

    resp = await client.get(
        f"/clients/{target_client.id}/findings/{finding.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == finding.id
    assert body["client_id"] == target_client.id
    assert body["drug"] == "ibuprofen"
    assert body["reaction"] == "gastrointestinal bleeding"
    assert body["bucket"] == "urgent"
    assert body["status"] == "pending_expedited"
    assert body["resolution_path"] == "escalated"
    assert body["model_confidence"] is None


@pytest.mark.asyncio
async def test_get_finding_404_cross_tenant(client, make_staff_user, make_client, seeded_finding):
    """Cross-tenant access returns 404 (FR-012)."""
    _owner_client, finding = seeded_finding
    other_client = await make_client()
    staff = await make_staff_user(role="reviewer")
    token = await login_token(client, staff.email)

    # Request the finding under a different client_id
    resp = await client.get(
        f"/clients/{other_client.id}/findings/{finding.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_finding_404_nonexistent(client, make_staff_user, make_client):
    """Non-existent finding id returns 404."""
    target_client = await make_client()
    staff = await make_staff_user(role="reviewer")
    token = await login_token(client, staff.email)

    resp = await client.get(
        f"/clients/{target_client.id}/findings/999999999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_finding_suspended_client(
    client, auth_app, make_staff_user, make_client, seeded_finding
):
    """Suspended client returns 400 CLIENT_SUSPENDED via get_acting_client (FR-013)."""
    from sqlalchemy import update

    from app.clients.models import Client

    target_client, finding = seeded_finding
    staff = await make_staff_user(role="reviewer")
    token = await login_token(client, staff.email)

    # Suspend the client
    factory = auth_app.state.session_factory
    async with factory() as s:
        async with s.begin():
            await s.execute(
                update(Client).where(Client.id == target_client.id).values(status="suspended")
            )

    resp = await client.get(
        f"/clients/{target_client.id}/findings/{finding.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
