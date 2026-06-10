# Lean modelserver image — installs ONLY the 'modelserver' uv group (no torch, no app deps).
# Target size < 500 MB (FR-009/D1). Use: uv sync --only-group modelserver --no-install-project
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install ONLY the modelserver group — no project deps, no torch (D1/FR-008)
COPY pyproject.toml uv.lock* ./
RUN uv sync --only-group modelserver --no-install-project --frozen \
    || uv sync --only-group modelserver --no-install-project

# Application code (modelserver package + committed model artifacts)
COPY modelserver ./modelserver

RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH="/app"

EXPOSE 8001

CMD ["uvicorn", "modelserver.main:app", "--host", "0.0.0.0", "--port", "8001"]
