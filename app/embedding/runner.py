"""Index build runner: orchestrates parse, chunk, embed, persist."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.embedding.chunking import Chunker
from app.embedding.enums import DocumentIndexStatus, IndexBuildRunStatus
from app.embedding.models import Chunk, IndexBuildRun
from app.embedding.router import ParseError, route
from app.embedding.service import IndexBuildService
from app.embedding.tokenizer import EmbedderTokenizer
from app.infra.modelserver_client import ModelserverClient

_log = structlog.get_logger(__name__)


async def index_build_runner(
    session_factory: Callable[[], AsyncSession],
    client_id: int,
    modelserver_client: ModelserverClient | None = None,
    triggered_by_user_id: int | None = None,
) -> IndexBuildRun:
    """Execute a full index build: parse → chunk → embed → persist (FR-009/FR-010/FR-025).

    Args:
        session_factory: Callable that returns an AsyncSession.
        client_id: The client to index for.
        modelserver_client: ModelserverClient instance; if None, created from settings.
        triggered_by_user_id: ID of the user who triggered the build (for audit).

    Returns:
        The completed IndexBuildRun with status and counts.
    """
    settings = get_settings()

    # Create the run first (or get the in-flight one — FR-026). Doing this before anything that
    # can fail (e.g. tokenizer loading) means every failure path can finish the run as FAILED
    # instead of leaving a stuck 'running' row that blocks all future builds for this client.
    async with session_factory() as session:
        async with session.begin():
            run, _ = await IndexBuildService.create_run(session, client_id, triggered_by_user_id)
            run_id = run.id

    _log.info("index build run started", client_id=client_id, run_id=run_id)

    try:
        # Initialize tokenizer and chunker (exact token counting — FR-025)
        tokenizer = EmbedderTokenizer(tokenizer_path=settings.embedder_tokenizer_path)
        chunker = Chunker(
            tokenizer=tokenizer,
            target_tokens=settings.chunk_target_tokens,
            overlap_ratio=settings.chunk_overlap_ratio,
            max_tokens=settings.chunk_max_tokens,
        )

        # Verify embedder version at startup (FR-025)
        if settings.embedder_model_version:
            try:
                await EmbedderTokenizer.verify_embedder_version(
                    modelserver_client, settings.embedder_model_version
                )
            except Exception as e:
                _log.error("embedder version mismatch", error=str(e), exc_info=True)
                async with session_factory() as session:
                    async with session.begin():
                        await IndexBuildService.finish_run(
                            session, run_id, IndexBuildRunStatus.FAILED
                        )
                return run

        # Get documents to index (not_indexed/errored_transient + active watchlist)
        async with session_factory() as session:
            documents = await IndexBuildService.get_documents_to_index(session, client_id)

        _log.info(
            "documents to index",
            client_id=client_id,
            run_id=run_id,
            document_count=len(documents),
        )

        # Track counters across document processing
        documents_processed = 0
        documents_errored = 0
        documents_skipped = 0
        chunks_created = 0

        # Process each document with per-document atomicity
        for document in documents:
            success, doc_chunks = await _process_document(
                session_factory,
                run_id,
                document,
                tokenizer,
                chunker,
                modelserver_client,
                client_id,
            )
            if success is None:
                documents_skipped += 1
            elif success:
                documents_processed += 1
                chunks_created += doc_chunks
            else:
                documents_errored += 1

        # Update run with final counters and status (counters live only in-process across
        # the per-document transactions, so they must be written back here — FR-010).
        async with session_factory() as session:
            async with session.begin():
                run = await IndexBuildService.finish_run(
                    session,
                    run_id,
                    documents_processed=documents_processed,
                    documents_errored=documents_errored,
                    documents_skipped=documents_skipped,
                    chunks_created=chunks_created,
                )

        _log.info(
            "index build run finished",
            client_id=client_id,
            run_id=run_id,
            status=run.status,
            documents_processed=documents_processed,
            documents_errored=documents_errored,
            documents_skipped=documents_skipped,
            chunks_created=chunks_created,
        )

    except Exception as e:
        _log.error("unexpected error during index build", error=str(e), exc_info=True)
        async with session_factory() as session:
            async with session.begin():
                await IndexBuildService.finish_run(session, run_id, IndexBuildRunStatus.FAILED)

    return run


async def _process_document(
    session_factory: Callable[[], AsyncSession],
    run_id: int,
    document: Any,
    tokenizer: EmbedderTokenizer,
    chunker: Chunker,
    modelserver_client: ModelserverClient,
    client_id: int,
) -> tuple[bool | None, int]:
    """Process a single document: parse → chunk → embed → persist (atomic per-doc, FR-028).

    Args:
        session_factory: Callable that returns an AsyncSession.
        run_id: The index build run ID.
        document: The Document ORM object.
        tokenizer: Tokenizer for token counting.
        chunker: Chunker for splitting text.
        modelserver_client: Client for embedding requests.
        client_id: Tenant client ID.

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

    # Extract text for embedding
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
            # Extract embedding and version from result dict
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

            chunk = Chunk(
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
            chunk_rows.append(chunk)

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
