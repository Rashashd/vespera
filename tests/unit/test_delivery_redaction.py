"""Unit (US1/Polish): delivery error/reason values are PII-free before persistence (FR-024).

Scope = log/trace/error values only. The rendered report body delivered to its OWN client is the
intended deliverable and is intentionally NOT redacted.
"""

import httpx
import pytest

from app.delivery.n8n_client import N8nClient, N8nDeliveryError
from app.delivery.service import _scrub


class TestDeliveryErrorScrubbing:
    def test_scrub_redacts_email_and_ssn(self):
        out = _scrub("delivery to patient john.doe@example.com failed; SSN 123-45-6789")
        assert "john.doe@example.com" not in out
        assert "123-45-6789" not in out
        assert "<EMAIL_ADDRESS>" in out
        assert "<US_SSN>" in out

    def test_scrub_redacts_secret_token(self):
        out = _scrub("auth failed token=sk-ant-abcdefghijklmnopqrstuvwxyz123456")
        assert "sk-ant-abcdefghijklmnopqrstuvwxyz123456" not in out

    def test_scrub_none_and_empty(self):
        assert _scrub(None) is None
        assert _scrub("") is None

    def test_scrub_bounded_length(self):
        assert len(_scrub("x" * 5000)) <= 500


class TestN8nErrorMessagesArePiiFree:
    @pytest.mark.asyncio
    async def test_http_error_message_is_status_only(self, monkeypatch):
        async def boom(self, payload):
            raise httpx.HTTPStatusError(
                "patient john@example.com 123-45-6789",  # message would carry PII if surfaced
                request=httpx.Request("POST", "http://n8n"),
                response=httpx.Response(403, request=httpx.Request("POST", "http://n8n")),
            )

        monkeypatch.setattr("app.delivery.n8n_client.N8nClient._post", boom)
        client = N8nClient("http://n8n/webhook")
        try:
            await client.send({"x": 1})
            raise AssertionError("expected N8nDeliveryError")
        except N8nDeliveryError as exc:
            msg = str(exc)
            assert "john@example.com" not in msg
            assert "123-45-6789" not in msg
            assert "403" in msg  # only the status code is surfaced
