"""Unit (US1): delivery trigger handler enqueue + n8n client send/error paths."""

from types import SimpleNamespace

import httpx
import pytest

from app.delivery.handlers import make_on_report_approved
from app.delivery.n8n_client import N8nClient, N8nDeliveryError
from app.domain.events import ReportApproved


class TestOnReportApproved:
    @pytest.mark.asyncio
    async def test_enqueues_deliver_job_with_deterministic_id(self, monkeypatch):
        calls: list[tuple] = []

        async def fake_enqueue(name, **kw):
            calls.append((name, kw))

        monkeypatch.setattr("app.delivery.handlers.enqueue", fake_enqueue)
        app = SimpleNamespace(state=SimpleNamespace(arq=object()))
        handler = make_on_report_approved(app)

        event = ReportApproved(
            actor_id=1, actor_type="human", client_id=2, report_id=42, report_type="batch"
        )
        await handler(event, session=None)  # on_report_approved does not touch the session

        assert len(calls) == 1
        name, kw = calls[0]
        assert name == "task_deliver_report"
        assert kw["job_id"] == "deliver:42"
        assert kw["report_id"] == 42
        assert kw["app_state"] is app.state


class TestN8nClientErrors:
    @pytest.mark.asyncio
    async def test_unconfigured_webhook_raises(self):
        with pytest.raises(N8nDeliveryError):
            await N8nClient("").send({"x": 1})

    @pytest.mark.asyncio
    async def test_transport_error_wrapped(self, monkeypatch):
        async def boom(self, payload):
            raise httpx.ConnectError("connection refused")

        monkeypatch.setattr("app.delivery.n8n_client.N8nClient._post", boom)
        with pytest.raises(N8nDeliveryError) as ei:
            await N8nClient("http://n8n/webhook").send({"x": 1})
        # PII-free: class-name only, not the raw message.
        assert "ConnectError" in str(ei.value)

    def test_configured_property(self):
        assert N8nClient("http://n8n").configured is True
        assert N8nClient("").configured is False
