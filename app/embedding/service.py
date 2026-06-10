"""Base database operations for chunks, indexing state, and runs."""

from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

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
    async def finish_run(
        session: AsyncSession, run_id: int, status: str | None = None
    ) -> IndexBuildRun | None:
        """Mark a run as finished; derive status if not provided (FR-010).

        Status derivation:
        - If documents_errored > 0 AND documents_processed > 0 → partial_success
        - If documents_errored > 0 → failed
        - Otherwise → success

        Returns the updated run or None if not found.
        """
        stmt = select(IndexBuildRun).where(IndexBuildRun.id == run_id)
        run = (await session.execute(stmt)).scalars().first()
        if not run:
            return None

        # Derive status if not explicitly provided
        if status is None:
            if run.documents_errored > 0:
                if run.documents_processed > 0:
                    status = IndexBuildRunStatus.PARTIAL_SUCCESS
                else:
                    status = IndexBuildRunStatus.FAILED
            else:
                status = IndexBuildRunStatus.SUCCESS

        run.status = status
        run.finished_at = datetime.utcnow()
        await session.flush()
        return run

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
        stmt = select(DocumentIndexState).where(DocumentIndexState.document_id == document_id)
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
        stmt = select(DocumentIndexState).where(DocumentIndexState.document_id == document_id)
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
    async def get_documents_to_index(session: AsyncSession, client_id: int) -> list[Document]:
        """Get documents ready for indexing for a client (FR-020, FR-009).

        Returns documents that are:
        - Linked to at least one active watchlist (FR-020)
        - In state: not_indexed OR errored_transient (eligible for processing)
        - NOT already indexed or in permanent error state

        Idempotency guarantee: excludes indexed/indexed_empty/errored_permanent.
        """
        # Subquery: get document IDs linked to at least one active watchlist
        active_watchlist_docs = (
            select(DocumentWatchlist.document_id)
            .distinct()
            .join(Watchlist, DocumentWatchlist.watchlist_id == Watchlist.id)
            .where(Watchlist.is_active.is_(True))
        )

        # Main query: get documents with eligible status
        stmt = (
            select(Document)
            .where(
                and_(
                    Document.client_id == client_id,
                    Document.id.in_(active_watchlist_docs),
                )
            )
            .outerjoin(
                DocumentIndexState,
                Document.id == DocumentIndexState.document_id,
            )
            .where(
                or_(
                    # Not yet indexed at all
                    DocumentIndexState.id.is_(None),
                    # Transient failure (eligible for retry)
                    DocumentIndexState.status == DocumentIndexStatus.ERRORED_TRANSIENT,
                    # Not yet indexed status
                    DocumentIndexState.status == DocumentIndexStatus.NOT_INDEXED,
                )
            )
            .distinct()
        )

        return (await session.execute(stmt)).scalars().all()
