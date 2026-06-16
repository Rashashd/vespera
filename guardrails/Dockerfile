# Lean guardrails sidecar image — installs ONLY the 'guardrails' uv group (no torch, no
# onnxruntime, no app deps). The rails engine is pure-Python heuristics. Constitution VI.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install ONLY the guardrails group — no project deps, no torch (Constitution VI).
COPY pyproject.toml uv.lock* ./
RUN uv sync --only-group guardrails --no-install-project --frozen \
    || uv sync --only-group guardrails --no-install-project

# Application code (guardrails sidecar package only).
COPY guardrails ./guardrails

RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH="/app"

EXPOSE 8002

CMD ["uvicorn", "guardrails.main:app", "--host", "0.0.0.0", "--port", "8002"]
