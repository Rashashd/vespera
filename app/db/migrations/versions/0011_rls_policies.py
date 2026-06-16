"""Row-Level Security: ENABLE+FORCE RLS + tenant_isolation policies + grants to pantera_app.

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-16

Applies a role-aware tenant_isolation policy to every client_id-bearing table (clients keys on
its own id). users/audit_log are documented exemptions. The least-privilege runtime role
pantera_app is created at DB bootstrap (compose init / CI step), NOT here; this migration only
GRANTs table privileges to it and guards each GRANT so a missing role gives a clear error.
Runs on the privileged role (database_url); pantera bypasses RLS so migrations/seed are unaffected.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, scope_column). clients scopes on its own id; everything else on client_id.
_POLICIED_TABLES: list[tuple[str, str]] = [
    ("clients", "id"),
    ("watchlists", "client_id"),
    ("watchlist_items", "client_id"),
    ("watchlist_budget_usage", "client_id"),
    ("documents", "client_id"),
    ("document_sources", "client_id"),
    ("document_watchlists", "client_id"),
    ("ingestion_runs", "client_id"),
    ("ingestion_run_sources", "client_id"),
    ("source_watermarks", "client_id"),
    ("chunks", "client_id"),
    ("document_index_state", "client_id"),
    ("index_build_runs", "client_id"),
    ("findings", "client_id"),
    ("reports", "client_id"),
    ("report_findings", "client_id"),
    ("report_followups", "client_id"),
    ("llm_usage", "client_id"),
    ("watchlist_cycles", "client_id"),
    ("dead_letter", "client_id"),
    ("user_watchlist_scope", "client_id"),
]

_APP_ROLE = "pantera_app"

# Staff/system (is_staff='on') see all rows; otherwise scope to the GUC client id. NULLIF makes
# an unset GUC default-deny (no client matches), and current_setting(...,true) tolerates unset.
_PREDICATE = (
    "current_setting('app.is_staff', true) = 'on' "
    "OR {col} = NULLIF(current_setting('app.current_client_id', true), '')::bigint"
)


def upgrade() -> None:
    # Fail loudly if the bootstrap role is missing (it is provisioned outside the migration).
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_APP_ROLE}') THEN
                RAISE EXCEPTION
                    'role {_APP_ROLE} must be created at DB bootstrap before migration 0011';
            END IF;
        END
        $$;
        """)
    # Schema + table/sequence access for the least-privilege role (USAGE only; never owner).
    # Grant on ALL tables — including the EXEMPT users/audit_log, which the app reads/writes at
    # runtime (login, audit). RLS independently filters only the policied tables below.
    op.execute(f"GRANT USAGE ON SCHEMA public TO {_APP_ROLE}")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {_APP_ROLE}"
    )
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {_APP_ROLE}")

    for table, scope_col in _POLICIED_TABLES:
        predicate = _PREDICATE.format(col=scope_col)
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )


def downgrade() -> None:
    for table, _scope_col in _POLICIED_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute(
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public FROM {_APP_ROLE}"
    )
    op.execute(f"REVOKE USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public FROM {_APP_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {_APP_ROLE}")
    # The role itself is bootstrap-managed; do NOT drop it here.
