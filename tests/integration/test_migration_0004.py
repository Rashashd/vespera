"""Integration test: migration 0004 up + down integrity (T053)."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("PANTERA_INTEGRATION"),
    reason="requires the Compose stack (Vault + Postgres + Redis)",
)


async def test_migration_0004_tables_exist(auth_app):
    """After migration 0004 all six ingestion tables and the mesh columns exist (T053)."""
    from sqlalchemy import text

    engine = auth_app.state.engine

    async with engine.connect() as conn:
        # Check all six new tables exist.
        expected_tables = {
            "documents",
            "document_sources",
            "document_watchlists",
            "ingestion_runs",
            "ingestion_run_sources",
            "source_watermarks",
        }

        result = await conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
            )
        )
        existing_tables = {row[0] for row in result}
        missing = expected_tables - existing_tables
        assert not missing, f"Tables missing after 0004 upgrade: {missing}"

        # Check additive columns on watchlist_items.
        result = await conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'watchlist_items'"
            )
        )
        columns = {row[0] for row in result}
        assert "mesh_validity" in columns, "mesh_validity column missing from watchlist_items"
        assert "mesh_canonical" in columns, "mesh_canonical column missing from watchlist_items"

        # Check CHECK constraint on mesh_validity.
        result = await conn.execute(
            text(
                "SELECT constraint_name FROM information_schema.table_constraints "
                "WHERE table_schema = 'public' AND table_name = 'watchlist_items' "
                "AND constraint_type = 'CHECK'"
            )
        )
        check_names = {row[0] for row in result}
        assert (
            "ck_watchlist_items_mesh_validity" in check_names
        ), "mesh_validity CHECK constraint missing"
