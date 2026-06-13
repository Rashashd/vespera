"""Index build runner: orchestrates per-document indexing across a client's pending documents.

Per-document work (parse → chunk → embed → persist) lives in document_indexer.process_document;
the after-index triage hook lives in triage_trigger.trigger_triage.
"""

from collections.abc import Callable
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.embedding.chunking import Chunker
from app.embedding.document_indexer import process_document
from app.embedding.enums import IndexBuildRunStatus
from app.embedding.models import IndexBuildRun
from app.embedding.service import IndexBuildService
from app.embedding.tokenizer import EmbedderTokenizer
from app.infra.modelserver_client import ModelserverClient

_log = structlog.get_logger(__name__)


async def index_build_runner(
    session_factory: Callable[[], AsyncSession],
    client_id: int,
    modelserver_client: ModelserverClient | None = None,
    triggered_by_user_id: int | None = None,
    dispatcher: Any = None,
    app_state: Any = None,
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
            success, doc_chunks = await process_document(
                session_factory,
                run_id,
                document,
                tokenizer,
                chunker,
                modelserver_client,
                client_id,
                dispatcher,
                app_state,
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
