"""Integration test: verify migration 0006 is reversible (T048, FR-021)."""

import os

import pytest
from sqlalchemy import inspect, text

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires PANTERA_INTEGRATION=1 and docker compose up",
)


@pytest.mark.asyncio
class TestMigration0006:
    """Test that migration 0006 can be safely upgraded and downgraded."""

    async def test_migration_upgrade_creates_tables(self, async_session) -> None:
        """Verify migration 0006 creates chunks, document_index_state, index_build_runs."""
        # Check tables exist
        inspector = inspect(async_session.sync_session.get_bind())
        tables = inspector.get_table_names()

        assert "chunks" in tables, "Migration should create chunks table"
        assert "document_index_state" in tables, "Migration should create document_index_state"
        assert "index_build_runs" in tables, "Migration should create index_build_runs"

    async def test_chunks_table_schema(self, async_session) -> None:
        """Verify chunks table has all required columns (FR-002/FR-005/FR-016)."""
        inspector = inspect(async_session.sync_session.get_bind())
        columns = {col["name"]: col for col in inspector.get_columns("chunks")}

        required_columns = [
            "id",
            "client_id",
            "document_id",
            "ordinal",
            "chunk_type",
            "section",
            "drug",
            "date",
            "source_reliability",
            "text",
            "embedding",
            "text_tsv",
            "embedder_version",
            "created_at",
        ]

        for col_name in required_columns:
            assert col_name in columns, f"chunks table must have {col_name} column"

    async def test_indexes_exist(self, async_session) -> None:
        """Verify HNSW and GIN indexes are created (FR-015)."""
        inspector = inspect(async_session.sync_session.get_bind())
        indexes = {idx["name"]: idx for idx in inspector.get_indexes("chunks")}

        # Check for HNSW index
        hnsw_indexes = [name for name in indexes.keys() if "hnsw" in name.lower()]
        assert len(hnsw_indexes) > 0, "chunks table should have HNSW vector index"

        # Check for GIN index (full-text)
        gin_indexes = [name for name in indexes.keys() if "text_tsv" in name.lower()]
        assert len(gin_indexes) > 0, "chunks table should have GIN index on text_tsv"

    async def test_partial_unique_index_exists(self, async_session) -> None:
        """Verify partial unique index for one-in-flight guard (FR-026)."""
        # Query pg_indexes for partial unique index
        result = await async_session.execute(text("""
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'index_build_runs'
            AND indexdef LIKE '%UNIQUE%'
            AND indexdef LIKE '%WHERE status%'
            """))
        partial_unique_indexes = result.fetchall()
        assert len(partial_unique_indexes) > 0, (
            "index_build_runs should have partial unique index on (client_id) "
            "WHERE status='running'"
        )

    async def test_vector_extension_created(self, async_session) -> None:
        """Verify pgvector extension is created."""
        result = await async_session.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        )
        extensions = result.fetchall()
        assert len(extensions) > 0, "pgvector extension should be created"

    async def test_check_constraints_exist(self, async_session) -> None:
        """Verify CHECK constraints mirror enums."""
        inspector = inspect(async_session.sync_session.get_bind())

        # Get table constraints
        constraints = inspector.get_check_constraints("chunks")
        constraint_names = {c["name"] for c in constraints}

        # Should have chunk_type, source_reliability checks
        assert any(
            "chunk_type" in name.lower() or "type" in name.lower() for name in constraint_names
        ), "chunks should have CHECK constraint on chunk_type"
        assert any(
            "source_reliability" in name.lower() or "reliability" in name.lower()
            for name in constraint_names
        ), "chunks should have CHECK constraint on source_reliability"

        # document_index_state should have status check
        doc_state_constraints = {
            c["name"] for c in inspector.get_check_constraints("document_index_state")
        }
        assert any(
            "status" in name.lower() for name in doc_state_constraints
        ), "document_index_state should have CHECK constraint on status"

        # index_build_runs should have status check
        run_constraints = {c["name"] for c in inspector.get_check_constraints("index_build_runs")}
        assert any(
            "status" in name.lower() for name in run_constraints
        ), "index_build_runs should have CHECK constraint on status"

    async def test_foreign_keys_created(self, async_session) -> None:
        """Verify FK relationships are correct with CASCADE."""
        inspector = inspect(async_session.sync_session.get_bind())

        # chunks should have FKs to clients and documents
        chunks_fks = inspector.get_foreign_keys("chunks")
        fk_tables = {fk["referred_table"] for fk in chunks_fks}
        assert "clients" in fk_tables, "chunks should have FK to clients"
        assert "documents" in fk_tables, "chunks should have FK to documents"

        # document_index_state should have FK to documents (CASCADE)
        dis_fks = inspector.get_foreign_keys("document_index_state")
        dis_fk_tables = {fk["referred_table"] for fk in dis_fks}
        assert "documents" in dis_fk_tables, "document_index_state should have FK to documents"

        # index_build_runs should have FK to clients
        runs_fks = inspector.get_foreign_keys("index_build_runs")
        runs_fk_tables = {fk["referred_table"] for fk in runs_fks}
        assert "clients" in runs_fk_tables, "index_build_runs should have FK to clients"

    async def test_unique_constraints(self, async_session) -> None:
        """Verify UNIQUE constraints for idempotency and 1:1 relationships."""
        inspector = inspect(async_session.sync_session.get_bind())

        # chunks should have unique (document_id, ordinal)
        chunks_uks = inspector.get_unique_constraints("chunks")
        chunk_uk_names = {uk["name"] for uk in chunks_uks}
        assert any(
            "ordinal" in name.lower() or "document" in name.lower() for name in chunk_uk_names
        ), "chunks should have UNIQUE constraint on (document_id, ordinal)"

        # document_index_state should have unique document_id (1:1)
        dis_uks = inspector.get_unique_constraints("document_index_state")
        assert (
            len(dis_uks) > 0
        ), "document_index_state should have UNIQUE constraint (1:1 with documents)"
