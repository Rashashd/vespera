"""Base database operations for chunks, indexing state, and runs."""

from datetime import datetime

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.clients.models import Watchlist
from app.embedding.enums import DocumentIndexStatus, IndexBuildRunStatus
from app.embedding.models import Chunk, DocumentIndexState, IndexBuildRun
from app.ingestion.models import Document, DocumentWatchlist


class IndexBuildService:
    """Database operations for chunks, indexing state, and build runs."""

    @staticmethod
    async def create_run(
        session: AsyncSession, client_id: int, triggered_by_user_id: int | None = None
    ) -> IndexBuildRun:
        """Create a new index build run; returns existing if one is in-flight (FR-026).

        The partial-unique index on (client_id) WHERE status='running' ensures at most one
        per client is in-flight.
        """
        # Check if a run is already in-flight for this client
        stmt = select(IndexBuildRun).where(
            and_(
                IndexBuildRun.client_id == client_id,
                IndexBuildRun.status == IndexBuildRunStatus.RUNNING,
            )
        )
        existing = (await session.execute(stmt)).scalars().first()
        if existing:
            return existing

        # Create a new run
        run = IndexBuildRun(
            client_id=client_id,
            triggered_by_user_id=triggered_by_user_id,
            status=IndexBuildRunStatus.RUNNING,
        )
        session.add(run)
        await session.flush()
        return run

    @staticmethod
    async def finish_run(session: AsyncSession, run_id: int, status: str) -> None:
        """Mark a run as finished with the given status."""
        stmt = select(IndexBuildRun).where(IndexBuildRun.id == run_id)
        run = (await session.execute(stmt)).scalars().first()
        if run:
            run.status = status
            run.finished_at = datetime.utcnow()
            await session.flush()

    @staticmethod
    async def get_run(session: AsyncSession, run_id: int) -> IndexBuildRun | None:
        """Get a run by ID."""
        stmt = select(IndexBuildRun).where(IndexBuildRun.id == run_id)
        return (await session.execute(stmt)).scalars().first()

    @staticmethod
    async def list_runs(
        session: AsyncSession, client_id: int, limit: int = 50
    ) -> list[IndexBuildRun]:
        """List runs for a client (most recent first)."""
        stmt = (
            select(IndexBuildRun)
            .where(IndexBuildRun.client_id == client_id)
            .order_by(IndexBuildRun.started_at.desc())
            .limit(limit)
        )
        return (await session.execute(stmt)).scalars().all()

    @staticmethod
    async def get_or_create_index_state(
        session: AsyncSession, document_id: int, client_id: int
    ) -> DocumentIndexState:
        """Get or lazily create a document index state (FR-010)."""
        stmt = select(DocumentIndexState).where(
            DocumentIndexState.document_id == document_id
        )
        state = (await session.execute(stmt)).scalars().first()
        if state:
            return state

        state = DocumentIndexState(
            document_id=document_id,
            client_id=client_id,
            status=DocumentIndexStatus.NOT_INDEXED,
        )
        session.add(state)
        await session.flush()
        return state

    @staticmethod
    async def set_index_state(
        session: AsyncSession,
        document_id: int,
        status: str,
        chunk_count: int = 0,
        embedder_version: str | None = None,
        attempts: int | None = None,
        last_error: str | None = None,
        last_run_id: int | None = None,
    ) -> None:
        """Update document index state."""
        stmt = select(DocumentIndexState).where(
            DocumentIndexState.document_id == document_id
        )
        state = (await session.execute(stmt)).scalars().first()
        if state:
            state.status = status
            if chunk_count:
                state.chunk_count = chunk_count
            if embedder_version:
                state.embedder_version = embedder_version
            if attempts is not None:
                state.attempts = attempts
            if last_error is not None:
                state.last_error = last_error
            if last_run_id is not None:
                state.last_run_id = last_run_id
            state.updated_at = datetime.utcnow()
            await session.flush()

    @staticmethod
    async def insert_chunks(session: AsyncSession, chunks: list[Chunk]) -> None:
        """Persist chunks; idempotent via unique (document_id, ordinal) constraint."""
        for chunk in chunks:
            session.add(chunk)
        await session.flush()

    @staticmethod
    async def get_documents_to_index(
        session: AsyncSession, client_id: int
    ) -> list[Document]:
        """Get documents ready for indexing for a client.

        Returns documents that are:
        - not_indexed OR errored_transient (eligible for processing)
        - Linked to at least one active watchlist (FR-020)
        """
        # Subquery: get document IDs linked to at least one active watchlist
        active_watchlist_docs = (
            select(DocumentWatchlist.document_id)
            .distinct()
            .join(Watchlist, DocumentWatchlist.watchlist_id == Watchlist.id)
            .where(Watchlist.is_active == True)
        )

        # Main query: get documents matching status + active watchlist
        stmt = (
            select(Document)
            .where(
                and_(
                    Document.client_id == client_id,
                    Document.id.in_(active_watchlist_docs),
                )
            )
            .join(
                DocumentIndexState,
                Document.id == DocumentIndexState.document_id,
                isouter=True,
            )
            .where(
                (DocumentIndexState.status.in_([
                    DocumentIndexStatus.NOT_INDEXED,
                    DocumentIndexStatus.ERRORED_TRANSIENT,
                ]))
                | (DocumentIndexState.id == None)  # Not yet indexed
            )
        )

        return (await session.execute(stmt)).scalars().all()

    @staticmethod
    def update_run_counts(
        session: Session,
        run_id: int,
        documents_processed: int = 0,
        chunks_created: int = 0,
        documents_skipped: int = 0,
        documents_errored: int = 0,
    ) -> None:
        """Atomically update run counters (sync version for transaction-local use)."""
        run = session.query(IndexBuildRun).filter(IndexBuildRun.id == run_id).first()
        if run:
            run.documents_processed += documents_processed
            run.chunks_created += chunks_created
            run.documents_skipped += documents_skipped
            run.documents_errored += documents_errored

