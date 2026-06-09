# Quickstart: Staff & Client Account Model

**Feature**: 004b-staff-and-clients · validation/run guide. Backend/API only. See
[contracts/](./contracts/) and [data-model.md](./data-model.md) for details.

## Prerequisites

- Local stack up: `docker compose up -d` (+ gitignored `docker-compose.override.yml` on this host).
- Secrets in Vault (`scripts/write_secrets.py`). Optionally set `bootstrap_manager_email` /
  `bootstrap_manager_password` in Vault; if unset, the documented dev default + force-change applies (D7).
- `PANTERA_INTEGRATION=1` for integration tests.

## Apply the migration

```powershell
uv run alembic upgrade head        # applies 0005: schema + dev reset + bootstrap manager
uv run alembic downgrade 0004      # reverts schema (data reset is one-way; see research D12)
uv run alembic upgrade head
```

Expected: `users` gains `user_type`/`client_scope`/`min_severity` (client_id nullable); `clients` gains
the three report columns; `user_watchlist_scope` created; exactly **one** bootstrap manager exists;
`documents`/`watchlists`/`watermarks` preserved. Re-running upgrade creates **no** duplicate manager.

## End-to-end validation scenarios

1. **Bootstrap → staff (US1, SC-001)**: log in as the bootstrap manager; `POST /staff` an admin and a
   reviewer; confirm each has `user_type=staff`, no `client_id`; log in as each.
2. **Cross-client action with target (US1, SC-002)**: as admin, `POST /clients/{A}/...` and
   `/clients/{B}/...`; confirm both permitted and audited with the correct `target_client_id`; confirm a
   request to a non-existent client → 404 and an action naming no client is impossible (no such route).
3. **Privilege guards (SC-003)**: admin `POST /staff` with `role=manager` → 403; demote/deactivate the
   last manager → 409 `LAST_MANAGER` (including self).
4. **Client lifecycle (US2, SC-004)**: manager `POST /clients`; `…/suspend` → new ingestion trigger for
   it refused, its documents still readable by staff; `…/reactivate` → triggers accepted again; confirm
   no hard-delete endpoint exists.
5. **Client-users + scope (US3, SC-005)**: admin `POST /clients/{A}/users` with `client_scope=scoped`,
   `min_severity=serious`, a subset of client A's watchlists; confirm stored; adding a client-B watchlist
   → 400 `CROSS_CLIENT_WATCHLIST`; creating with no `client_scope` → 400 `SCOPE_REQUIRED`.
6. **Report emails (US4, SC-006)**: admin `PATCH /clients/{A}/report-emails` (regular+urgent+threshold);
   malformed email → 400 unchanged; reviewer attempt → 403.
7. **Session freshness (US5, SC-007)**: log in as admin; manager demotes them; the admin's **next**
   request reflects the lower role without re-login. Suspend a client; its client-user's next request is
   refused. Token lifetime ~8h.
8. **Append-only audit (US5, SC-008)**: each sensitive write yields exactly one audit row naming actor +
   `target_client_id`; confirm no update/delete path mutates an audit row.

## Test commands

```powershell
uv run pytest tests/unit/test_authz_matrix.py tests/unit/test_scope_rules.py
$env:PANTERA_INTEGRATION=1; uv run pytest tests/integration -k "staff or client or lifecycle or freshness or migration_0005"
uv run ruff check app tests; uv run black --check app worker tests   # BOTH must pass
```

Expected: auth/account-write paths ≥95% line coverage; overall ≥80%.
