"""Unit tests for the audit query-scoping service (role visibility policy, FR-018)."""

from __future__ import annotations

from dataclasses import dataclass

from app.audit import service as audit_service
from app.auth.schemas import Role


@dataclass
class _Staff:
    role: str


def _sql(query) -> str:
    return str(query.compile(compile_kwargs={"literal_binds": True}))


def test_manager_scope_is_all_and_unfiltered_by_allowlist():
    q, scope = audit_service.build_scoped_query(_Staff(Role.MANAGER.value))
    assert scope == "all"
    assert audit_service.is_manager(_Staff(Role.MANAGER.value)) is True
    # A manager is NOT narrowed to the admin allowlist.
    assert "WatchlistActivationChanged" not in _sql(q)


def test_admin_scope_is_client_watchlist_and_restricted_to_allowlist():
    q, scope = audit_service.build_scoped_query(_Staff(Role.ADMIN.value))
    assert scope == "client_watchlist"
    assert audit_service.is_manager(_Staff(Role.ADMIN.value)) is False
    # An admin query is narrowed to the management/outcome allowlist.
    assert "WatchlistActivationChanged" in _sql(q)


def test_both_roles_exclude_auth_noise_events():
    for role in (Role.MANAGER.value, Role.ADMIN.value):
        sql = _sql(audit_service.build_scoped_query(_Staff(role))[0])
        assert "UserLoggedIn" in sql  # present as a NOT IN (...) exclusion
        assert "LoginFailed" in sql


def test_filters_apply_event_type_and_client_id():
    q, _ = audit_service.build_scoped_query(
        _Staff(Role.MANAGER.value), event_type="ReportApproved", client_id=42
    )
    sql = _sql(q)
    assert "ReportApproved" in sql
    assert "42" in sql
