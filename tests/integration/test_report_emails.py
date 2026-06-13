"""Report email delivery address integration tests (spec 4b, US4; FR-017/FR-018)."""

import os

import pytest

from tests.integration.conftest import login_token

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires the Compose stack (Vault + Postgres + Redis)",
)


async def test_admin_sets_report_emails(client, make_staff_user, make_client):
    """Admin can configure both delivery addresses and the urgent threshold."""
    admin = await make_staff_user(role="admin")
    target = await make_client()
    token = await login_token(client, admin.email)
    resp = await client.patch(
        f"/clients/{target.id}/report-emails",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "report_email_regular": "regular@pharma.com",
            "report_email_urgent": "urgent@pharma.com",
            "urgent_severity_threshold": "serious",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["report_email_regular"] == "regular@pharma.com"
    assert body["report_email_urgent"] == "urgent@pharma.com"
    assert body["urgent_severity_threshold"] == "serious"


async def test_partial_update_preserves_other_fields(client, make_staff_user, make_client):
    """Omitted fields are not overwritten; existing values are preserved (FR-017)."""
    admin = await make_staff_user(role="admin")
    target = await make_client()
    token = await login_token(client, admin.email)

    # Set both fields first
    await client.patch(
        f"/clients/{target.id}/report-emails",
        headers={"Authorization": f"Bearer {token}"},
        json={"report_email_regular": "regular@pharma.com", "report_email_urgent": "urg@p.com"},
    )

    # Update only the regular email
    resp = await client.patch(
        f"/clients/{target.id}/report-emails",
        headers={"Authorization": f"Bearer {token}"},
        json={"report_email_regular": "new@pharma.com"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["report_email_regular"] == "new@pharma.com"
    assert body["report_email_urgent"] == "urg@p.com"  # unchanged


async def test_malformed_email_rejected_unchanged(client, make_staff_user, make_client):
    """Malformed email in report_email_regular returns 400; stored value unchanged (FR-017)."""
    admin = await make_staff_user(role="admin")
    target = await make_client()
    token = await login_token(client, admin.email)

    # Set a valid email first
    await client.patch(
        f"/clients/{target.id}/report-emails",
        headers={"Authorization": f"Bearer {token}"},
        json={"report_email_regular": "valid@pharma.com"},
    )

    # Attempt to set invalid email
    resp = await client.patch(
        f"/clients/{target.id}/report-emails",
        headers={"Authorization": f"Bearer {token}"},
        json={"report_email_regular": "not-an-email"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "INVALID_EMAIL"

    # Verify stored value is unchanged
    detail_resp = await client.get(
        f"/clients/{target.id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert detail_resp.json()["report_email_regular"] == "valid@pharma.com"


async def test_reviewer_cannot_set_emails(client, make_staff_user, make_client):
    """Reviewer does not have admin access; PATCH report-emails → 403."""
    reviewer = await make_staff_user(role="reviewer")
    target = await make_client()
    token = await login_token(client, reviewer.email)
    resp = await client.patch(
        f"/clients/{target.id}/report-emails",
        headers={"Authorization": f"Bearer {token}"},
        json={"report_email_regular": "reg@pharma.com"},
    )
    assert resp.status_code == 403


async def test_set_emails_creates_audit_entry(client, make_staff_user, make_client, auth_app):
    """Updating report emails creates an audit entry (FR-021)."""
    from sqlalchemy import func, select

    from app.audit.models import AuditLog

    admin = await make_staff_user(role="admin")
    target = await make_client()
    token = await login_token(client, admin.email)

    factory = auth_app.state.session_factory
    async with factory() as s:
        before = await s.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.client_id == target.id,
                AuditLog.event_type == "ClientReportEmailChanged",
            )
        )

    await client.patch(
        f"/clients/{target.id}/report-emails",
        headers={"Authorization": f"Bearer {token}"},
        json={"report_email_regular": "audit@pharma.com"},
    )

    async with factory() as s:
        after = await s.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.client_id == target.id,
                AuditLog.event_type == "ClientReportEmailChanged",
            )
        )

    assert (after or 0) == (before or 0) + 1
