"""Per-document indexing: parse → chunk → embed → persist (atomic per document)."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.embedding.chunking import Chunker
from app.embedding.enums import DocumentIndexStatus
from app.embedding.models import Chunk
from app.embedding.parsers.base import ParseError
from app.embedding.parsers.router import route
from app.embedding.service import IndexBuildService
from app.embedding.tokenizer import EmbedderTokenizer
from app.embedding.triage_trigger import trigger_triage
from app.infra.modelserver_client import ModelserverClient

_log = structlog.get_logger(__name__)


async def process_document(
    session_factory: Callable[[], AsyncSession],
    run_id: int,
    document: Any,
    tokenizer: EmbedderTokenizer,
    chunker: Chunker,
    modelserver_client: ModelserverClient,
    client_id: int,
    dispatcher: Any = None,
    app_state: Any = None,
) -> tuple[bool | None, int]:
    """Process a single document: parse → chunk → embed → persist (atomic per-doc, FR-028).

    Returns:
        (success, chunk_count) where success is True/False/None (skipped).
    """
    # Check if document should be skipped (check state outside transaction first)
    async with session_factory() as session:
        index_state = await IndexBuildService.get_or_create_index_state(
            session, document.id, client_id
        )
        should_skip = index_state.status in (
            DocumentIndexStatus.INDEXED,
            DocumentIndexStatus.INDEXED_EMPTY,
            DocumentIndexStatus.ERRORED_PERMANENT,
        )

    if should_skip:
        _log.info(
            "skipping document already processed",
            client_id=client_id,
            document_id=document.id,
            run_id=run_id,
        )
        return (None, 0)

    # Select the best source payload (FR-024)
    from app.embedding.selection import select_source

    try:
        selected_source = select_source(document.sources)
    except ValueError as e:
        # Permanent failure: no valid source available
        _log.warning(
            "no valid source for document",
            client_id=client_id,
            document_id=document.id,
            run_id=run_id,
            error=str(e),
            transient=False,
        )
        async with session_factory() as session:
            async with session.begin():
                index_state = await IndexBuildService.get_or_create_index_state(
                    session, document.id, client_id
                )
                index_state.status = DocumentIndexStatus.ERRORED_PERMANENT
                index_state.attempts += 1
                index_state.last_error = str(e)[:255]
                index_state.updated_at = datetime.now(UTC)
                index_state.last_run_id = run_id
        return (False, 0)

    raw_payload = selected_source.raw_payload

    # Parse document (CPU-bound, run in thread)
    try:
        parsed_chunks = await asyncio.to_thread(route, selected_source.source, raw_payload)
    except ParseError as e:
        status = (
            DocumentIndexStatus.ERRORED_TRANSIENT
            if e.is_transient
            else DocumentIndexStatus.ERRORED_PERMANENT
        )
        _log.warning(
            "parse error for document",
            client_id=client_id,
            document_id=document.id,
            run_id=run_id,
            error=str(e),
            transient=e.is_transient,
        )
        async with session_factory() as session:
            async with session.begin():
                index_state = await IndexBuildService.get_or_create_index_state(
                    session, document.id, client_id
                )
                index_state.status = status
                index_state.attempts += 1
                index_state.last_error = str(e)[:255]
                index_state.last_run_id = run_id
                index_state.updated_at = datetime.now(UTC)
        return (False, 0)

    if not parsed_chunks:
        # Document parsed but yielded no chunks
        async with session_factory() as session:
            async with session.begin():
                index_state = await IndexBuildService.get_or_create_index_state(
                    session, document.id, client_id
                )
                index_state.status = DocumentIndexStatus.INDEXED_EMPTY
                index_state.chunk_count = 0
                index_state.embedder_version = (
                    (await modelserver_client.get_ready())
                    .get("models", {})
                    .get("embedder", {})
                    .get("sha256")
                )
                index_state.attempts += 1
                index_state.last_run_id = run_id
                index_state.updated_at = datetime.now(UTC)
        return (True, 0)

    # Chunk the parsed content
    chunked = chunker.chunk(parsed_chunks)
    chunk_texts = [c.text for c in chunked]

    # Embed chunks
    try:
        embeddings = await modelserver_client.embed_chunked(chunk_texts)
    except Exception as e:
        _log.warning(
            "embedding failed for document",
            client_id=client_id,
            document_id=document.id,
            run_id=run_id,
            error=str(e),
            transient=True,
        )
        async with session_factory() as session:
            async with session.begin():
                index_state = await IndexBuildService.get_or_create_index_state(
                    session, document.id, client_id
                )
                index_state.status = DocumentIndexStatus.ERRORED_TRANSIENT
                index_state.attempts += 1
                index_state.last_error = f"Embedding failed: {str(e)[:200]}"
                index_state.last_run_id = run_id
                index_state.updated_at = datetime.now(UTC)
        return (False, 0)

    # Build Chunk ORM objects and persist with per-document atomicity
    try:
        chunk_rows = []
        embedder_version = None

        for chunked_obj, embedding_result in zip(chunked, embeddings, strict=True):
            embedding_vector = embedding_result.get("embedding")
            model_version = embedding_result.get("model_version", {})
            embedder_version = model_version.get("sha256")

            # M5: Fail if embedder version is missing (no silent fallback)
            if not embedder_version:
                raise ValueError(
                    "Modelserver response missing embedder version (sha256); "
                    "cannot create versioned attestation"
                )

            # Validate embedding dimension (FR-016)
            if not isinstance(embedding_vector, list) or len(embedding_vector) != 768:
                dim = len(embedding_vector) if isinstance(embedding_vector, list) else "not a list"
                raise ValueError(f"Invalid embedding dimension: expected 768, got {dim}")

            chunk_rows.append(
                Chunk(
                    client_id=client_id,
                    document_id=document.id,
                    ordinal=chunked_obj.ordinal,
                    chunk_type=chunked_obj.chunk_type.value,
                    section=chunked_obj.section,
                    drug=None,  # Always NULL in v1 (FR-023)
                    date=document.published_at,
                    source_reliability=document.source_reliability,
                    text=chunked_obj.text,
                    embedding=embedding_vector,
                    embedder_version=embedder_version,
                )
            )

        # Persist chunks and state in one per-document transaction
        async with session_factory() as session:
            async with session.begin():
                await IndexBuildService.insert_chunks(session, chunk_rows)
                index_state = await IndexBuildService.get_or_create_index_state(
                    session, document.id, client_id
                )
                index_state.status = DocumentIndexStatus.INDEXED
                index_state.chunk_count = len(chunk_rows)
                index_state.embedder_version = embedder_version
                index_state.attempts += 1
                index_state.last_error = None
                index_state.last_run_id = run_id
                index_state.updated_at = datetime.now(UTC)

        _log.info(
            "document indexed",
            client_id=client_id,
            document_id=document.id,
            run_id=run_id,
            chunk_count=len(chunk_rows),
        )

        # Triage fires after embedding commit; failures are logged and swallowed (FR-009).
        if dispatcher is not None:
            await trigger_triage(
                session_factory=session_factory,
                document=document,
                chunk_texts=chunk_texts,
                client_id=client_id,
                modelserver_client=modelserver_client,
                dispatcher=dispatcher,
                app_state=app_state,
            )

        return (True, len(chunk_rows))

    except Exception as e:
        _log.error(
            "failed to persist chunks for document",
            client_id=client_id,
            document_id=document.id,
            run_id=run_id,
            error=str(e),
            exc_info=True,
        )
        async with session_factory() as session:
            async with session.begin():
                index_state = await IndexBuildService.get_or_create_index_state(
                    session, document.id, client_id
                )
                index_state.status = DocumentIndexStatus.ERRORED_TRANSIENT
                index_state.attempts += 1
                index_state.last_error = f"Persistence failed: {str(e)[:200]}"
                index_state.last_run_id = run_id
                index_state.updated_at = datetime.now(UTC)
        return (False, 0)
