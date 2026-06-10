"""Inference routes: POST /classify, POST /embed, GET /health, GET /ready.

All inference routes require X-Service-Token and are gated behind readiness.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request

from modelserver.auth import require_service_token
from modelserver.logging import get_logger
from modelserver.schemas import (
    ClassificationResult,
    ClassifyRequest,
    ClassifyResponse,
    EmbeddingResult,
    EmbedRequest,
    EmbedResponse,
    ModelVersion,
)

router = APIRouter()
_log = get_logger(__name__)

_READY_COUNTERS: dict[str, list[float]] = {"classify": [], "embed": []}
_MAX_WINDOW = 1000


def _record_latency(op: str, ms: float) -> None:
    """Keep a rolling window of latency samples for /ready observability (D11)."""
    buf = _READY_COUNTERS.setdefault(op, [])
    buf.append(ms)
    if len(buf) > _MAX_WINDOW:
        del buf[: len(buf) - _MAX_WINDOW]


def _percentile(buf: list[float], p: int) -> float | None:
    if not buf:
        return None
    sorted_buf = sorted(buf)
    idx = int(len(sorted_buf) * p / 100)
    return round(sorted_buf[min(idx, len(sorted_buf) - 1)], 2)


@router.get("/health")
async def health() -> dict:
    """Liveness: no auth, no inference — answers as soon as the process is up (FR-017)."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> dict:
    """Readiness: 200 only after both artifacts are loaded and validated (FR-017/D7)."""
    if not getattr(request.app.state, "ready", False):
        raise HTTPException(status_code=503, detail="Service not ready")
    return {
        "status": "ready",
        "models": request.app.state.model_versions,
        "latency_ms": {
            op: {
                "p50": _percentile(buf, 50),
                "p95": _percentile(buf, 95),
                "count": len(buf),
            }
            for op, buf in _READY_COUNTERS.items()
        },
    }


@router.post(
    "/classify",
    dependencies=[Depends(require_service_token)],
    response_model=ClassifyResponse,
)
async def classify(body: ClassifyRequest, request: Request) -> ClassifyResponse:
    """Adverse-event classification — batch ≤ 128, deterministic, version-stamped (US1)."""
    if not getattr(request.app.state, "ready", False):
        raise HTTPException(status_code=503, detail="Service not ready")

    t0 = time.perf_counter()
    predictions = request.app.state.classifier.predict(body.texts)
    latency_ms = (time.perf_counter() - t0) * 1000
    _record_latency("classify", latency_ms)

    mv_dict = request.app.state.manifest.model_version("classifier")
    mv = ModelVersion(**mv_dict)

    results = [
        ClassificationResult(confidence=conf, is_adverse=is_adv, model_version=mv)
        for conf, is_adv in predictions
    ]
    _log.info(
        "classify",
        operation="classify",
        batch_size=len(body.texts),
        latency_ms=round(latency_ms, 2),
        model_version=mv_dict["sha256"][:12],
    )
    return ClassifyResponse(model_version=mv, results=results)


@router.post(
    "/embed",
    dependencies=[Depends(require_service_token)],
    response_model=EmbedResponse,
)
async def embed(body: EmbedRequest, request: Request) -> EmbedResponse:
    """Medical embeddings — 768-dim L2-normalized, batch ≤ 128, deterministic (US2)."""
    if not getattr(request.app.state, "ready", False):
        raise HTTPException(status_code=503, detail="Service not ready")

    t0 = time.perf_counter()
    vectors = request.app.state.embedder.embed(body.texts)
    latency_ms = (time.perf_counter() - t0) * 1000
    _record_latency("embed", latency_ms)

    mv_dict = request.app.state.manifest.model_version("embedder")
    mv = ModelVersion(**mv_dict)

    results = [EmbeddingResult(embedding=vec, model_version=mv) for vec in vectors]
    _log.info(
        "embed",
        operation="embed",
        batch_size=len(body.texts),
        latency_ms=round(latency_ms, 2),
        model_version=mv_dict["sha256"][:12],
    )
    return EmbedResponse(model_version=mv, results=results)
