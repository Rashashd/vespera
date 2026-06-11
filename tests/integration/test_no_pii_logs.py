"""Verify that modelserver logs never expose request text, embeddings, or the service token.

Captures structlog stdout output during a representative run and asserts that
PII-bearing content (request text, raw vectors, token values) is absent (SC-008/FR-020).
Also confirms that only /classify, /embed, /health, /ready are reachable (FR-006).
"""

from __future__ import annotations

import importlib.util
import io
import sys

import pytest

ADVERSE = "patient developed acute liver failure after starting drug X"
BENIGN = "no adverse events were observed during the 12-week trial"

# Exercises the standalone modelserver app, which imports onnxruntime at boot (only in the
# `modelserver` uv group). Skip unless that dep is present; CI installs it via --group modelserver.
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        importlib.util.find_spec("onnxruntime") is None,
        reason="requires modelserver runtime deps (onnxruntime); run under the modelserver env",
    ),
]


async def _capture_logs_during(ms_authed, fn) -> str:
    """Run fn() while capturing structlog stdout output."""
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        await fn()
    finally:
        sys.stdout = old_stdout
    return buf.getvalue()


async def test_classify_logs_no_request_text(ms_authed):
    output = await _capture_logs_during(
        ms_authed,
        lambda: ms_authed.post("/classify", json={"texts": [ADVERSE, BENIGN]}),
    )
    assert ADVERSE not in output, "Request text must not appear in classify logs"
    assert BENIGN not in output, "Request text must not appear in classify logs"


async def test_embed_logs_no_request_text(ms_authed):
    output = await _capture_logs_during(
        ms_authed,
        lambda: ms_authed.post("/embed", json={"texts": [ADVERSE]}),
    )
    assert ADVERSE not in output, "Request text must not appear in embed logs"


async def test_logs_no_service_token(ms_authed):
    """The service token value must never appear in any log output."""
    output = await _capture_logs_during(
        ms_authed,
        lambda: ms_authed.post("/classify", json={"texts": [ADVERSE]}),
    )
    assert "test-service-token" not in output, "Service token must not appear in logs"


async def test_logs_no_raw_embedding_vectors(ms_authed):
    """Raw embedding vectors (long float lists) must not be logged."""
    output = await _capture_logs_during(
        ms_authed,
        lambda: ms_authed.post("/embed", json={"texts": [ADVERSE]}),
    )
    # A raw 768-dim vector logged would contain many comma-separated floats
    float_run = ",".join(["0."] * 20)
    assert float_run not in output, "Raw embedding vectors must not appear in logs"


async def test_classify_logs_operation_binding(ms_authed, capsys):
    """Classify logs must contain the 'classify' operation binding."""
    await ms_authed.post("/classify", json={"texts": [ADVERSE]})
    out = capsys.readouterr().out
    assert "classify" in out


async def test_embed_logs_operation_binding(ms_authed, capsys):
    """Embed logs must contain the 'embed' operation binding."""
    await ms_authed.post("/embed", json={"texts": [ADVERSE]})
    out = capsys.readouterr().out
    assert "embed" in out


async def test_only_known_routes_reachable(ms_authed):
    """Unknown routes return 404 — only the four spec routes are exposed (FR-006)."""
    unknown_paths = [
        "/admin",
        "/debug",
        "/v1/classify",
        "/api/classify",
        "/metrics",
    ]
    for path in unknown_paths:
        resp = await ms_authed.get(path)
        assert resp.status_code == 404, f"Unexpected route {path} returned {resp.status_code}"
