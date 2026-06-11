"""Integration test: verify migration 0006 schema (T048, FR-021)."""

import os

import pytest
from sqlalchemy import inspect, text

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires PANTERA_INTEGRATION=1 and docker compose up",
)


async def _inspect(async_session, fn):
    """Run a sync SQLAlchemy inspector call over the async connection (greenlet-safe)."""
    conn = await async_session.connection()
    return await conn.run_sync(lambda sync_conn: fn(inspect(sync_conn)))


@pytest.mark.asyncio
class TestMigration0006:
    """Test that migration 0006 created the expected schema objects."""

    async def test_migration_upgrade_creates_tables(self, async_session) -> None:
        """Verify migration 0006 creates chunks, document_index_state, index_build_runs."""
        tables = await _inspect(async_session, lambda insp: insp.get_table_names())
        assert "chunks" in tables, "Migration should create chunks table"
        assert "document_index_state" in tables, "Migration should create document_index_state"
        assert "index_build_runs" in tables, "Migration should create index_build_runs"

    async def test_chunks_table_schema(self, async_session) -> None:
        """Verify chunks table has all required columns (FR-002/FR-005/FR-016)."""
        columns = await _inspect(
            async_session, lambda insp: {col["name"] for col in insp.get_columns("chunks")}
        )
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
        indexes = await _inspect(
            async_session, lambda insp: {idx["name"] for idx in insp.get_indexes("chunks")}
        )
        assert any(
            "hnsw" in name.lower() for name in indexes
        ), "chunks table should have HNSW vector index"
        assert any(
            "text_tsv" in name.lower() for name in indexes
        ), "chunks table should have GIN index on text_tsv"

    async def test_partial_unique_index_exists(self, async_session) -> None:
        """Verify partial unique index for one-in-flight guard (FR-026)."""
        result = await async_session.execute(text("""
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'index_build_runs'
            AND indexdef LIKE '%UNIQUE%'
            AND indexdef LIKE '%status%'
            """))
        assert (
            len(result.fetchall()) > 0
        ), "index_build_runs should have a partial unique index WHERE status='running'"

    async def test_vector_extension_created(self, async_session) -> None:
        """Verify pgvector extension is created."""
        result = await async_session.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        )
        assert len(result.fetchall()) > 0, "pgvector extension should be created"

    async def test_check_constraints_exist(self, async_session) -> None:
        """Verify CHECK constraints mirror enums."""
        chunk_names = await _inspect(
            async_session,
            lambda insp: {c["name"] for c in insp.get_check_constraints("chunks")},
        )
        assert any(
            "type" in name.lower() for name in chunk_names
        ), "chunks should have CHECK constraint on chunk_type"
        assert any(
            "reliability" in name.lower() for name in chunk_names
        ), "chunks should have CHECK constraint on source_reliability"

        dis_names = await _inspect(
            async_session,
            lambda insp: {c["name"] for c in insp.get_check_constraints("document_index_state")},
        )
        assert any(
            "status" in name.lower() for name in dis_names
        ), "document_index_state should have CHECK constraint on status"

        run_names = await _inspect(
            async_session,
            lambda insp: {c["name"] for c in insp.get_check_constraints("index_build_runs")},
        )
        assert any(
            "status" in name.lower() for name in run_names
        ), "index_build_runs should have CHECK constraint on status"

    async def test_foreign_keys_created(self, async_session) -> None:
        """Verify FK relationships are correct."""
        chunks_fk = await _inspect(
            async_session,
            lambda insp: {fk["referred_table"] for fk in insp.get_foreign_keys("chunks")},
        )
        assert "clients" in chunks_fk, "chunks should have FK to clients"
        assert "documents" in chunks_fk, "chunks should have FK to documents"

        dis_fk = await _inspect(
            async_session,
            lambda insp: {
                fk["referred_table"] for fk in insp.get_foreign_keys("document_index_state")
            },
        )
        assert "documents" in dis_fk, "document_index_state should have FK to documents"

        runs_fk = await _inspect(
            async_session,
            lambda insp: {fk["referred_table"] for fk in insp.get_foreign_keys("index_build_runs")},
        )
        assert "clients" in runs_fk, "index_build_runs should have FK to clients"

    async def test_unique_constraints(self, async_session) -> None:
        """Verify UNIQUE constraints for idempotency and 1:1 relationships."""
        chunk_uk = await _inspect(
            async_session,
            lambda insp: {uk["name"] for uk in insp.get_unique_constraints("chunks")},
        )
        assert any(
            "ordinal" in name.lower() or "document" in name.lower() for name in chunk_uk
        ), "chunks should have UNIQUE constraint on (document_id, ordinal)"

        dis_uk = await _inspect(
            async_session,
            lambda insp: insp.get_unique_constraints("document_index_state"),
        )
        assert (
            len(dis_uk) > 0
        ), "document_index_state should have UNIQUE constraint (1:1 with documents)"
