"""Index build runner: orchestrates parse, chunk, embed, persist."""

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.embedding.chunking import Chunker
from app.embedding.enums import DocumentIndexStatus, IndexBuildRunStatus
from app.embedding.models import Chunk, DocumentIndexState, IndexBuildRun
from app.embedding.router import ParseError, route
from app.embedding.service import IndexBuildService
from app.embedding.tokenizer import EmbedderTokenizer
from app.infra.modelserver_client import ModelserverClient
from app.ingestion.enums import SourceName

logger = logging.getLogger(__name__)


async def index_build_runner(
    session_factory: Callable[[], AsyncSession],
    client_id: int,
    modelserver_client: ModelserverClient | None = None,
    triggered_by_user_id: int | None = None,
) -> IndexBuildRun:
    """Execute a full index build for a client: parse → chunk → embed → persist (FR-009/FR-010/FR-025).

    Args:
        session_factory: Callable that returns an AsyncSession.
        client_id: The client to index for.
        modelserver_client: ModelserverClient instance; if None, created from settings.
        triggered_by_user_id: ID of the user who triggered the build (for audit).

    Returns:
        The completed IndexBuildRun with status and counts.
    """
    session = session_factory()
    settings = get_settings()

    # Initialize tokenizer and chunker
    try:
        tokenizer = EmbedderTokenizer(tokenizer_path=settings.embedder_tokenizer_path)
    except Exception as e:
        logger.error(f"Failed to load tokenizer: {e}")
        raise

    chunker = Chunker(
        tokenizer=tokenizer,
        target_tokens=settings.chunk_target_tokens,
        overlap_ratio=settings.chunk_overlap_ratio,
        max_tokens=settings.chunk_max_tokens,
    )

    # Initialize modelserver client if not provided
    if modelserver_client is None:
        modelserver_client = ModelserverClient.from_settings(settings)

    # Create the run (or get in-flight run if one exists — FR-026)
    run = await IndexBuildService.create_run(session, client_id, triggered_by_user_id)
    logger.info(
        "Index build run started",
        extra={"client_id": client_id, "run_id": run.id},
    )

    try:
        # Verify embedder version at startup (FR-025)
        if settings.embedder_model_version:
            try:
                await EmbedderTokenizer.verify_embedder_version(
                    modelserver_client, settings.embedder_model_version
                )
            except Exception as e:
                logger.error(f"Embedder version mismatch: {e}")
                run.status = IndexBuildRunStatus.FAILED
                await IndexBuildService.finish_run(session, run.id, run.status)
                await session.commit()
                return run

        # Get documents to index for this client (not_indexed / errored_transient + active watchlist)
        documents = await IndexBuildService.get_documents_to_index(session, client_id)
        logger.info(
            f"Found {len(documents)} documents to index",
            extra={"client_id": client_id, "run_id": run.id},
        )

        # Process each document
        for document in documents:
            await _process_document(
                session,
                run,
                document,
                tokenizer,
                chunker,
                modelserver_client,
                client_id,
            )

        # Finalize run status
        if run.documents_errored > 0 and run.documents_processed > 0:
            run.status = IndexBuildRunStatus.PARTIAL_SUCCESS
        elif run.documents_errored > 0:
            run.status = IndexBuildRunStatus.FAILED
        else:
            run.status = IndexBuildRunStatus.SUCCESS

        await IndexBuildService.finish_run(session, run.id, run.status)
        logger.info(
            "Index build run finished",
            extra={
                "client_id": client_id,
                "run_id": run.id,
                "status": run.status,
                "documents_processed": run.documents_processed,
                "chunks_created": run.chunks_created,
            },
        )

    except Exception as e:
        logger.error(f"Unexpected error during index build: {e}", exc_info=True)
        run.status = IndexBuildRunStatus.FAILED
        await IndexBuildService.finish_run(session, run.id, run.status)

    finally:
        await session.commit()
        await session.close()

    return run


async def _process_document(
    session: AsyncSession,
    run: IndexBuildRun,
    document: Any,
    tokenizer: EmbedderTokenizer,
    chunker: Chunker,
    modelserver_client: ModelserverClient,
    client_id: int,
) -> None:
    """Process a single document: parse → chunk → embed → persist (atomic, FR-028).

    Args:
        session: Database session.
        run: The index build run being executed.
        document: The Document ORM object.
        tokenizer: Tokenizer for token counting.
        chunker: Chunker for splitting text.
        modelserver_client: Client for embedding requests.
        client_id: Tenant client ID.
    """
    extra_log = {"client_id": client_id, "document_id": document.id, "run_id": run.id}

    # Get or create the index state
    index_state = await IndexBuildService.get_or_create_index_state(
        session, document.id, client_id
    )

    # Skip already-indexed documents (idempotency)
    if index_state.status in (
        DocumentIndexStatus.INDEXED,
        DocumentIndexStatus.INDEXED_EMPTY,
        DocumentIndexStatus.ERRORED_PERMANENT,
    ):
        run.documents_skipped += 1
        logger.info("Skipping document (already processed)", extra=extra_log)
        return

    # Select the best source payload (FR-024)
    from app.embedding.selection import select_source

    try:
        selected_source = select_source(document.document_sources)
    except ValueError as e:
        # Permanent failure: no valid source available
        logger.warning(
            f"No valid source for document {document.id}: {e}",
            extra={**extra_log, "transient": False},
        )
        index_state.status = DocumentIndexStatus.ERRORED_PERMANENT
        index_state.attempts += 1
        index_state.last_error = str(e)[:255]
        index_state.updated_at = datetime.utcnow()
        index_state.last_run_id = run.id
        run.documents_errored += 1
        await session.flush()
        return

    raw_payload = selected_source.raw_payload

    # Parse document (CPU-bound, run in thread)
    try:
        parsed_chunks = await asyncio.to_thread(
            route, selected_source.source, raw_payload
        )
    except ParseError as e:
        status = (
            DocumentIndexStatus.ERRORED_TRANSIENT
            if e.is_transient
            else DocumentIndexStatus.ERRORED_PERMANENT
        )
        logger.warning(
            f"Parse error for document {document.id}: {e}",
            extra={"client_id": client_id, "document_id": document.id, "transient": e.is_transient},
        )
        index_state.status = status
        index_state.attempts += 1
        index_state.last_error = str(e)[:255]  # Truncate for DB
        index_state.last_run_id = run.id
        index_state.updated_at = datetime.utcnow()
        run.documents_errored += 1
        await session.flush()
        return

    if not parsed_chunks:
        # Document parsed but yielded no chunks
        index_state.status = DocumentIndexStatus.INDEXED_EMPTY
        index_state.chunk_count = 0
        index_state.embedder_version = (
            (await modelserver_client.get_ready()).get("models", {}).get("embedder", {}).get("sha256")
        )
        index_state.attempts += 1
        index_state.last_run_id = run.id
        index_state.updated_at = datetime.utcnow()
        run.documents_processed += 1
        await session.flush()
        return

    # Chunk the parsed content
    chunked = chunker.chunk(parsed_chunks)

    # Extract text for embedding
    chunk_texts = [c.text for c in chunked]

    # Embed chunks
    try:
        embeddings = await modelserver_client.embed_chunked(chunk_texts)
    except Exception as e:
        logger.warning(
            f"Embedding failed for document {document.id}: {e}",
            extra={"client_id": client_id, "document_id": document.id, "transient": True},
        )
        index_state.status = DocumentIndexStatus.ERRORED_TRANSIENT
        index_state.attempts += 1
        index_state.last_error = f"Embedding failed: {str(e)[:200]}"
        index_state.last_run_id = run.id
        index_state.updated_at = datetime.utcnow()
        run.documents_errored += 1
        await session.flush()
        return

    # Build Chunk ORM objects and persist in atomic transaction
    try:
        chunk_rows = []
        embedder_version = None

        for i, (chunked_obj, embedding_result) in enumerate(zip(chunked, embeddings)):
            # Extract embedding and version from result dict
            embedding_vector = embedding_result.get("embedding")
            model_version = embedding_result.get("model_version", {})
            embedder_version = model_version.get("sha256", "unknown")

            # Validate embedding dimension (FR-016)
            if not isinstance(embedding_vector, list) or len(embedding_vector) != 768:
                raise ValueError(
                    f"Invalid embedding dimension: expected 768, got {len(embedding_vector) if isinstance(embedding_vector, list) else 'not a list'}"
                )

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

        # Persist chunks (idempotency guard via unique constraint)
        await IndexBuildService.insert_chunks(session, chunk_rows)

        # Atomically update state (same transaction as chunks)
        index_state.status = DocumentIndexStatus.INDEXED
        index_state.chunk_count = len(chunk_rows)
        index_state.embedder_version = embedder_version
        index_state.attempts += 1
        index_state.last_error = None
        index_state.last_run_id = run.id
        index_state.updated_at = datetime.utcnow()

        # Update run counters
        run.documents_processed += 1
        run.chunks_created += len(chunk_rows)

        await session.flush()
        logger.info(
            f"Document indexed: {len(chunk_rows)} chunks",
            extra={"client_id": client_id, "document_id": document.id},
        )

    except Exception as e:
        logger.error(f"Failed to persist chunks for document {document.id}: {e}", exc_info=True)
        index_state.status = DocumentIndexStatus.ERRORED_TRANSIENT
        index_state.attempts += 1
        index_state.last_error = f"Persistence failed: {str(e)[:200]}"
        index_state.last_run_id = run.id
        index_state.updated_at = datetime.utcnow()
        run.documents_errored += 1
        await session.flush()

