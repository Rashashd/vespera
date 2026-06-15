"""Security regression tests for the spec-10 portal/passage object-level authorization fixes.

Covers the three hardening fixes:
- findings endpoint: client-users may only read findings of approved+sent reports (not in-workflow);
  staff see all.
- passage endpoint: client-users may only read chunks cited by their approved reports (not the whole
  corpus); staff may read any chunk for the acting client.
- portal list: excludes in-workflow reports, and attributes expedited reports lacking a direct
  watchlist_id to a single owning watchlist via document_watchlists (FR-030).
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.embedding.models import Chunk
from app.reports.models import Report, ReportFinding
from app.triage.models import Finding


async def _login(auth_app, email: str, password: str = "Abcdef1!") -> AsyncClient:
    """Return a fresh ASGI client authenticated as the given user."""
    c = AsyncClient(transport=ASGITransport(app=auth_app), base_url="http://test")
    resp = await c.post("/auth/jwt/login", data={"username": email, "password": password})
    resp.raise_for_status()
    c.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
    return c


async def _seed_report(
    session,
    *,
    client_id: int,
    document_id: int,
    status: str,
    drug: str,
    report_type: str = "expedited",
    watchlist_id: int | None = None,
    corroboration_sources: list | None = None,
) -> Report:
    """Insert a report + one finding + the report_finding link; return the report."""
    finding = Finding(
        client_id=client_id,
        document_id=document_id,
        drug=drug,
        reaction="rhabdomyolysis",
        bucket="urgent",
        status="reported",
        resolution_path="model",
    )
    session.add(finding)
    await session.flush()

    report = Report(
        client_id=client_id,
        report_type=report_type,
        status=status,
        watchlist_id=watchlist_id,
        corroboration_sources=corroboration_sources,
    )
    session.add(report)
    await session.flush()

    session.add(
        ReportFinding(
            report_id=report.id,
            finding_id=finding.id,
            client_id=client_id,
            report_type=report_type,
            state="included",
        )
    )
    await session.commit()
    return report


@pytest.mark.integration
@pytest.mark.asyncio
async def test_clientuser_cannot_read_inworkflow_findings(
    async_session, make_client, make_document, make_user, make_staff_user, auth_app
) -> None:
    """E1: a client-user gets 404 on findings of an in-workflow report; 200 on an approved one."""
    cl = await make_client()
    doc1 = await make_document(client_id=cl.id)
    doc2 = await make_document(client_id=cl.id)
    drafted = await _seed_report(
        async_session, client_id=cl.id, document_id=doc1.id, status="drafted", drug="drugA"
    )
    approved = await _seed_report(
        async_session, client_id=cl.id, document_id=doc2.id, status="approved", drug="drugB"
    )

    cu = await make_user(client_id=cl.id, role="client_user")
    cuc = await _login(auth_app, cu.email)
    try:
        assert (await cuc.get(f"/clients/{cl.id}/reports/{drafted.id}/findings")).status_code == 404
        assert (
            await cuc.get(f"/clients/{cl.id}/reports/{approved.id}/findings")
        ).status_code == 200
    finally:
        await cuc.aclose()

    # Staff (reviewer) sees findings of the in-workflow report.
    rev = await make_staff_user(role="reviewer")
    rc = await _login(auth_app, rev.email)
    try:
        resp = await rc.get(f"/clients/{cl.id}/reports/{drafted.id}/findings")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
    finally:
        await rc.aclose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_clientuser_passage_scoped_to_cited_chunks(
    async_session, make_client, make_document, make_user, make_staff_user, auth_app
) -> None:
    """E2: a client-user may read a chunk cited by an approved report, but not an uncited one."""
    cl = await make_client()
    doc = await make_document(client_id=cl.id)
    cited = Chunk(
        client_id=cl.id,
        document_id=doc.id,
        ordinal=0,
        chunk_type="text",
        source_reliability="peer_reviewed",
        text="cited passage",
        embedding=[0.0] * 768,
        embedder_version="t",
    )
    uncited = Chunk(
        client_id=cl.id,
        document_id=doc.id,
        ordinal=1,
        chunk_type="text",
        source_reliability="peer_reviewed",
        text="uncited passage",
        embedding=[0.0] * 768,
        embedder_version="t",
    )
    async_session.add_all([cited, uncited])
    await async_session.flush()
    await _seed_report(
        async_session,
        client_id=cl.id,
        document_id=doc.id,
        status="approved",
        drug="drugC",
        corroboration_sources=[{"passage_chunk_ids": [cited.id]}],
    )

    cu = await make_user(client_id=cl.id, role="client_user")
    cuc = await _login(auth_app, cu.email)
    try:
        assert (await cuc.get(f"/clients/{cl.id}/passages/{cited.id}")).status_code == 200
        assert (await cuc.get(f"/clients/{cl.id}/passages/{uncited.id}")).status_code == 404
    finally:
        await cuc.aclose()

    # Staff may read the uncited chunk (unrestricted for the acting client).
    rev = await make_staff_user(role="reviewer")
    rc = await _login(auth_app, rev.email)
    try:
        assert (await rc.get(f"/clients/{cl.id}/passages/{uncited.id}")).status_code == 200
    finally:
        await rc.aclose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_portal_list_excludes_inworkflow_reports(
    async_session, make_client, make_document, authed_reviewer_client
) -> None:
    """Portal list returns only approved+sent reports — never in-workflow ones."""
    cl = await make_client()
    doc1 = await make_document(client_id=cl.id)
    doc2 = await make_document(client_id=cl.id)
    await _seed_report(
        async_session, client_id=cl.id, document_id=doc1.id, status="drafted", drug="drugD"
    )
    approved = await _seed_report(
        async_session, client_id=cl.id, document_id=doc2.id, status="approved", drug="drugE"
    )

    resp = await authed_reviewer_client.get(f"/clients/{cl.id}/portal/reports")
    assert resp.status_code == 200
    ids = [r["id"] for r in resp.json()]
    assert ids == [approved.id]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_portal_attributes_expedited_to_owning_watchlist(
    async_session, make_client, make_watchlist, make_document, authed_reviewer_client
) -> None:
    """FR-030: an approved expedited report with NULL watchlist_id is attributed via junction."""
    cl = await make_client()
    wl = await make_watchlist(client_id=cl.id)
    doc = await make_document(client_id=cl.id, watchlist_id=wl.id)  # creates DocumentWatchlist link
    report = await _seed_report(
        async_session,
        client_id=cl.id,
        document_id=doc.id,
        status="approved",
        report_type="expedited",
        watchlist_id=None,
        drug="drugF",
    )

    # Filter by the owning watchlist → report appears with the resolved watchlist_id.
    resp = await authed_reviewer_client.get(f"/clients/{cl.id}/portal/reports?watchlist_id={wl.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == report.id
    assert data[0]["watchlist_id"] == wl.id

    # Filter by a different watchlist → not present.
    other = await authed_reviewer_client.get(
        f"/clients/{cl.id}/portal/reports?watchlist_id={wl.id + 999}"
    )
    assert other.json() == []
