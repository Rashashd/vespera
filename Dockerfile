# Shared image for the API and ARQ worker — installs deps via uv, runs as non-root.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# uv for reproducible installs.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first for layer caching.
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-group modelserver --no-group training --frozen || uv sync --no-dev --no-group modelserver --no-group training

# Application code.
COPY app ./app
COPY worker ./worker
COPY scripts ./scripts
COPY alembic.ini ./alembic.ini

RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH="/app"

EXPOSE 8000
