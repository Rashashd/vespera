"""Unit tests for embedder-version-mismatch refusal logic (T011 / US1 / FR-004)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_session(versions: list[str]) -> AsyncMock:
    """Build a mock async session returning the given distinct embedder_version rows."""
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = versions
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.mark.asyncio
async def test_version_match_ok():
    """No exception when stored version matches live sha."""
    from app.rag.query_embed import assert_index_version

    sha = "a" * 64
    session = _make_session([sha])
    await assert_index_version(session, client_id=1, embedder_sha=sha)  # no raise


@pytest.mark.asyncio
async def test_empty_corpus_ok():
    """Empty chunk set (no stored versions) should not raise (FR-004)."""
    from app.rag.query_embed import assert_index_version

    session = _make_session([])
    await assert_index_version(session, client_id=1, embedder_sha="a" * 64)  # no raise


@pytest.mark.asyncio
async def test_version_mismatch_raises():
    """Stored sha differs from live sha → EmbedderVersionMismatch (FR-004)."""
    from app.rag.query_embed import EmbedderVersionMismatch, assert_index_version

    stored_sha = "a" * 64
    live_sha = "b" * 64
    session = _make_session([stored_sha])
    with pytest.raises(EmbedderVersionMismatch):
        await assert_index_version(session, client_id=1, embedder_sha=live_sha)


@pytest.mark.asyncio
async def test_multiple_stored_versions_raises():
    """Two distinct stored shas are always a mismatch (should never happen, but guard anyway)."""
    from app.rag.query_embed import EmbedderVersionMismatch, assert_index_version

    session = _make_session(["a" * 64, "b" * 64])
    with pytest.raises(EmbedderVersionMismatch):
        await assert_index_version(session, client_id=1, embedder_sha="a" * 64)
