"""Query normalization, embedding cache, and embedder-version safety for RAG retrieval."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any

import structlog
from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.embedding.models import Chunk
from app.infra.modelserver_client import ModelserverClient

_log = structlog.get_logger(__name__)


class EmbedderVersionMismatch(Exception):
    """Raised when the live embedder sha differs from the client's stored chunk versions."""


def normalize_query(query: str) -> str:
    """NFKC-normalize, strip, lower-case, and collapse internal whitespace."""
    normalized = unicodedata.normalize("NFKC", query)
    stripped = normalized.strip().lower()
    return re.sub(r"\s+", " ", stripped)


def query_hash(query: str) -> str:
    """Return the sha256 hex digest of the normalized query (for PII-free logging)."""
    return hashlib.sha256(normalize_query(query).encode()).hexdigest()


def cache_key(embedder_sha: str, query: str) -> str:
    """Build the Redis cache key scoped to the embedder version (FR-017)."""
    norm = normalize_query(query)
    qhash = hashlib.sha256(norm.encode()).hexdigest()
    return f"rag:qemb:{embedder_sha}:{qhash}"


async def assert_index_version(session: AsyncSession, client_id: int, embedder_sha: str) -> None:
    """Refuse retrieval if the client's chunk index was built with a different embedder.

    Empty index (no chunks) is always OK — caller should return empty results.
    Raises EmbedderVersionMismatch when the stored versions don't match the live sha.
    """
    rows = (
        (
            await session.execute(
                select(distinct(Chunk.embedder_version)).where(Chunk.client_id == client_id)
            )
        )
        .scalars()
        .all()
    )

    if not rows:
        return  # empty corpus — OK

    stored = set(rows)
    if stored != {embedder_sha}:
        raise EmbedderVersionMismatch(
            f"client {client_id} index built with {stored!r}; " f"live embedder is {embedder_sha!r}"
        )


async def get_query_embedding(
    redis: Any,
    ms_client: ModelserverClient,
    settings: Any,
    app_state: Any,
    query: str,
) -> tuple[list[float], str]:
    """Return (embedding_vector, embedder_sha) for the query, served from Redis when warm.

    The embedder sha is memoized on app_state.embedder_sha after the first live embed.
    Cache outages are non-fatal: the query proceeds via a live embed (FR-018).
    """
    # Resolve memoized sha (may be empty on first call)
    embedder_sha: str = getattr(app_state, "embedder_sha", "") or getattr(
        settings, "embedder_model_version", ""
    )

    # Attempt cache hit only when we have the sha (cache key requires it)
    if embedder_sha and redis is not None:
        key = cache_key(embedder_sha, query)
        try:
            cached = await redis.get(key)
            if cached is not None:
                return json.loads(cached), embedder_sha
        except Exception:
            _log.warning("rag.cache.unavailable", op="get")

    # Live embed
    results = await ms_client.embed([query])
    vector: list[float] = results[0]["embedding"]
    embedder_sha = results[0]["model_version"]["sha256"]

    # Memoize sha on app.state
    try:
        app_state.embedder_sha = embedder_sha
    except Exception:
        pass

    # Write-through to cache (best-effort)
    if redis is not None:
        key = cache_key(embedder_sha, query)
        try:
            ttl = getattr(settings, "query_embedding_cache_ttl", 3600)
            await redis.set(key, json.dumps(vector), ex=ttl)
        except Exception:
            _log.warning("rag.cache.unavailable", op="set")

    return vector, embedder_sha
