"""Unit tests for report delivery-status derivation from per-channel attempts (US1/FR-004a)."""

from app.delivery.service import derive_report_status
from app.reports.enums import ReportStatus


class TestDeriveReportStatus:
    """delivered = all delivered; delivery_failed = any failed; otherwise sent."""

    def test_single_channel_delivered(self):
        assert derive_report_status(["delivered"]) == ReportStatus.DELIVERED

    def test_all_channels_delivered(self):
        assert derive_report_status(["delivered", "delivered"]) == ReportStatus.DELIVERED

    def test_any_channel_failed(self):
        assert derive_report_status(["delivered", "failed"]) == ReportStatus.DELIVERY_FAILED

    def test_failed_takes_precedence_over_pending(self):
        # A failed channel fails the report even while another is still pending.
        assert derive_report_status(["pending", "failed"]) == ReportStatus.DELIVERY_FAILED

    def test_mixed_pending_is_sent(self):
        assert derive_report_status(["delivered", "pending"]) == ReportStatus.SENT

    def test_all_pending_is_sent(self):
        assert derive_report_status(["pending", "pending"]) == ReportStatus.SENT

    def test_no_attempts_is_none(self):
        assert derive_report_status([]) is None
