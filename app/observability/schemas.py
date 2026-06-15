"""Pydantic schemas for the cost dashboard and ops metrics endpoints (spec 10)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class CallSiteBreakdown(BaseModel):
    cost_usd: str
    calls: int


class WindowFilter(BaseModel):
    from_: datetime | None = None
    to: datetime | None = None

    model_config = {"populate_by_name": True}


class CostDashboard(BaseModel):
    """Aggregated per-client LLM cost view (FR-021/034)."""

    client_id: int
    total_cost_usd: str
    total_input_tokens: int
    total_output_tokens: int
    call_count: int
    by_call_site: dict[str, CallSiteBreakdown]
    window: dict


class QueueMetrics(BaseModel):
    pending: int
    expedited: int
    batch: int


class SlaMetrics(BaseModel):
    overdue: int
    due_soon: int
    met_pct: float


class RedraftMetrics(BaseModel):
    avg_revisions: float
    hit_cap: int


class OpsDashboard(BaseModel):
    """Live operational metrics from reports/findings (FR-021a). delivery is null until spec 13."""

    client_id: int
    by_status: dict[str, int]
    queue: QueueMetrics
    sla: SlaMetrics
    redraft: RedraftMetrics
    delivery: None
    window: dict
