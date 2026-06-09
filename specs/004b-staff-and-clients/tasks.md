# Tasks: Staff & Client Account Model (Agency Foundation Revision)

**Feature**: 004b-staff-and-clients · **Branch**: `004b-staff-and-clients`
**Input**: [plan.md](./plan.md), [spec.md](./spec.md), [data-model.md](./data-model.md),
[research.md](./research.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md)

Tests are INCLUDED — the constitution gates auth/account-write paths at ≥95% coverage and the success
criteria (SC-001..011) require verification. Paths are exact and relative to repo root.

**MVP** = Phase 1 (Setup) + Phase 2 (Foundational) + Phase 3 (US1). Each later phase is an
independently testable increment. **Phase 4 (existing-route migration) is required before the broader
app works for staff** and before US2+ operate on real client data — see Dependencies.

---

## Phase 1: Setup

- [X] T001 [P] Update `app/core/config.py`: set `auth_token_ttl_seconds` 1800 → 28800 (~8h, FR-019); add optional `bootstrap_manager_email` and `bootstrap_manager_password` settings (default empty, NOT added to `_REQUIRED_SECRETS` — D7, so no `ci.yml` change).
- [X] T002 [P] In `app/auth/schemas.py`, add `UserType` StrEnum (`staff`,`client`) and `ClientScope` StrEnum (`full`,`scoped`); extend `Role` with `MANAGER="manager"` and `CLIENT_USER="client_user"` (D1/D2/D4).

## Phase 2: Foundational (blocking — must complete before any user story)

- [X] T003 [P] In `app/auth/models.py`, add `user_type`, `client_scope`, `min_severity` columns to `User`; make `client_id` nullable; add `ck_users_type_client`, `ck_users_client_scope`, `ck_users_min_severity` constraints; keep the unique email index (D1/D3).
- [X] T004 [P] In `app/clients/models.py`, add `report_email_regular`, `report_email_urgent`, `urgent_severity_threshold` (+`ck_clients_urgent_threshold`) to `Client`; add the new `UserWatchlistScope` model (FK `users`/`watchlists` ON DELETE CASCADE, UNIQUE `(user_id,watchlist_id)`, indexes) (D4/D5/D6).
- [X] T005 Create `app/db/migrations/versions/0005_staff_and_clients.py` (down_revision `0004`) — SCHEMA step: alter `users` (new columns, nullable `client_id`, drop+recreate `ck_users_role` to 4 roles, add integrity CHECKs), alter `clients` (report columns + threshold CHECK), create `user_watchlist_scope` (D2/D12).
- [X] T006 In `0005_staff_and_clients.py`, add the DATA step (depends T005): FK-safe deletes (`ingestion_run_sources` → `ingestion_runs` → user-authored `audit_log` rows → `users`), preserving documents/watchlists/watermarks. **The migration does NOT insert the bootstrap manager** — seeding is delegated to `ensure_manager()` (T007/T008) so the password is hashed in Python and seeding stays single-sourced/idempotent (C2). Write a matching `downgrade()` that drops the new schema and restores the 2-role CHECK (data reset one-way, documented).
- [X] T007 [P] Create `app/auth/bootstrap.py` with idempotent `ensure_manager(session, settings)` — create the bootstrap manager (hashing the password via the existing `password_helper`) **only if no active manager exists**; read optional Vault creds, with a documented dev fallback + force-change intent (D8). This is the **sole** manager-seed path (C2).
- [X] T008 Wire `bootstrap.ensure_manager()` into the startup sequence in `app/core/lifespan.py` (after secrets/DB ready) as the idempotent seed/safety net (D8).
- [X] T009 [P] In `app/domain/events.py`, add `ClientReactivated`, `ClientReportEmailChanged`, `ClientUserCreated`, `ClientUserScopeChanged`, `WatchlistActivationChanged` (all carry `target_client_id`); confirm `ClientCreated`/`ClientSuspended`/`UserCreated`/`UserRoleChanged`/`UserDeactivated` reused (D11, FR-027).
- [X] T010 [P] In `app/audit/handler.py`, persist `target_client_id` from events that carry it (the acted-upon client; staff actor `client_id` is NULL) (D11/FR-021).
- [X] T011 In `app/auth/dependencies.py`, add guards: `require_manager`, `require_staff`, `require_admin` (manager|admin, cross-client), `current_active_principal` (re-reads user each request; for client-users also rejects when their client `status!='active'`), and `acting_client(client_id)` dependency (loads/validates target client; 404 missing / not-own-for-client-user, 400 `CLIENT_SUSPENDED` for new work) (D9/D10, contracts/authz-model.md).

## Phase 3: User Story 1 — Internal staff operate across all clients (P1) 🎯 MVP

**Goal**: Cross-client staff identity + manager-owned staff accounts + acting-client scoping + audit.
**Independent test**: Seed bootstrap manager → create staff admin+reviewer → each signs in (no home
client) → admin acts on an existing client only when naming a valid one; audited by target client.

- [X] T012 [P] [US1] Unit test the authz matrix (role × user_type × action) in `tests/unit/test_authz_matrix.py`.
- [X] T013 [P] [US1] Integration test staff accounts in `tests/integration/test_staff_accounts.py`: manager creates staff; only manager mints managers; last-manager guard (incl. self); `user_type`/`client_id` rejected from body.
- [X] T014 [P] [US1] Integration test acting-client context in `tests/integration/test_acting_client.py`: staff action requires a valid named client; missing/non-existent refused; audit records `target_client_id`.
- [X] T015 [US1] Add staff schemas (`StaffUserCreate`, `StaffUserUpdate`, `StaffUserOut`) in `app/auth/schemas.py` (no `user_type`/`client_id` in request bodies).
- [X] T016 [US1] Add `_active_manager_count()` last-manager guard + manager-mint guard helper in `app/auth/manager.py` (mirrors spec-2 last-admin guard).
- [X] T017 [US1] Create `app/auth/routes_staff.py`: `POST/GET/PATCH /staff` (manager-only via `require_manager`), with `UserCreated`/`UserRoleChanged`/`UserDeactivated` audit and the guards from T016 (contracts/staff-accounts.md).
- [X] T018 [US1] Retire the legacy client-scoped admin user routes in `app/auth/routes_users.py` (remove; client-user management moves to Phase 6) and delete now-dead helpers.
- [X] T019 [US1] In `app/main.py`, register `routes_staff` router and remove the legacy `users_router` include.

**Checkpoint**: A manager can administer staff; staff act cross-client by named target; audited. MVP demonstrable.

## Phase 4: Existing-Route Migration to Cross-Client (C1 + FR-006/FR-027) ⚠️ required for the live app

**Goal**: Make the spec-3/4 routes work under the new model — they currently authorize via
`user.client_id`, which is **NULL for staff** and would break. Rewire them to `acting_client` so staff
operate cross-client (admin triggers ingestion for ANY client, FR-006) and client-users stay own-client.
Includes the new FR-027 staff-admin **watchlist (de)activation**.
**Independent test**: As a staff admin, browse/trigger/manage any client's watchlists/runs/documents by
naming the client; as a client-user, only your own client; deactivate one watchlist and confirm only it
stops ingesting while the client stays active.
**Depends on**: Phase 2 (esp. `acting_client`, T011). Can run in parallel with Phase 3.

- [ ] T020 [P] Integration test cross-client existing routes in `tests/integration/test_existing_routes_crossclient.py`: staff reach any client by `{client_id}`; client-users own-only (404 otherwise); admin triggers ingestion for any client; single-watchlist deactivation blocks only that watchlist while the client stays active (FR-006/FR-027).
- [ ] T021 Migrate `app/clients/routes_watchlists.py` to the `{client_id}` acting-client model + staff cross-client authz (client-users own-only); ADD staff-admin watchlist activate/deactivate (the existing `watchlists.is_active`) with `WatchlistActivationChanged` audit (FR-027); remove `user.client_id` reliance.
- [ ] T022 Migrate `app/ingestion/routes_ingestion.py` (trigger + run-status/list) to `acting_client`: a staff admin may trigger ingestion for ANY client (FR-006); reviewers/admins read runs cross-client; client-users own-only. Refuse triggers on `suspended` clients and `inactive` watchlists.
- [ ] T023 Migrate `app/ingestion/routes_documents.py` (browse) to `acting_client`/staff cross-client read + client-user own-client scoping; remove `user.client_id` reliance.
- [ ] T024 Update lookups in `app/clients/service.py` / `app/ingestion/service.py` that assumed own-client (e.g., `get_watchlist`) to use the validated acting client; audit-sweep for any remaining `user.client_id` use on staff-reachable paths.

**Checkpoint**: The whole existing app surface works under the agency model; FR-006 and FR-027 satisfied.

## Phase 5: User Story 2 — Manager manages the client roster (P1)

**Goal**: Manager create / soft-delete (suspend) / reactivate clients; staff read the roster; data preserved.
**Independent test**: Manager creates a client; suspends it (new runs refused, data readable);
reactivates it; non-manager refused; no hard-delete path.

- [X] T025 [P] [US2] Integration test client lifecycle in `tests/integration/test_client_lifecycle.py`: create/suspend/reactivate; preserve documents/watchlists; new-run refusal on suspended; roster list (staff) vs mutate (manager); no hard-delete.
- [X] T026 [US2] Add client lifecycle + detail schemas (`ClientCreate`, `ClientOut`) in `app/clients/schemas.py`.
- [X] T027 [US2] Add lifecycle service functions (`create_client`, `suspend_client`→`status='suspended'`, `reactivate_client`→`status='active'`, `list_clients`) in `app/clients/service.py` (D5).
- [X] T028 [US2] Update `app/clients/routes_clients.py`: `POST /clients` + `POST /clients/{id}/suspend` + `POST /clients/{id}/reactivate` (`require_manager`), `GET /clients` + `GET /clients/{id}` (`require_staff`), with `ClientCreated`/`ClientSuspended`/`ClientReactivated` audit (contracts/client-lifecycle.md).

**Checkpoint**: Full client lifecycle owned by the manager; roster readable by all staff.

## Phase 6: User Story 3 — Client-side users scoped by severity and watchlist (P2)

**Goal**: Admin creates client-users with an explicit, least-privilege scope; cross-client watchlist refused.
**Independent test**: Admin creates a scoped client-user for a named client; cross-client watchlist
refused; creation without explicit scope refused; client-user cannot widen own scope; audited.

- [X] T029 [P] [US3] Unit test scope rules in `tests/unit/test_scope_rules.py`: empty/absent scope ⇒ no visibility (default-deny); `scoped` requires ≥1 of severity/watchlist; cross-client watchlist refused.
- [X] T030 [P] [US3] Integration test client-users in `tests/integration/test_client_users.py`: create + scope; `SCOPE_REQUIRED`; `CROSS_CLIENT_WATCHLIST`; scope change; immutable `user_type`/`client_id`.
- [X] T031 [US3] Add client-user schemas (`ClientUserCreate`, `ClientUserUpdate`, `ClientUserOut` with `client_scope`/`min_severity`/`watchlist_ids`) in `app/clients/schemas.py`.
- [X] T032 [US3] Add client-user + scope service in `app/clients/service.py`: create (force `user_type='client'`, validate explicit scope, validate each watchlist belongs to the client), scope-change, race-safe `user_watchlist_scope` upserts (`ON CONFLICT`) (D4/FR-014/FR-015).
- [X] T033 [US3] Create `app/clients/routes_client_users.py`: `POST/GET/PATCH /clients/{client_id}/users` (`require_admin` + `acting_client`) with `ClientUserCreated`/`ClientUserScopeChanged` audit (contracts/client-users.md).
- [X] T034 [US3] Register `routes_client_users` router in `app/main.py`.

**Checkpoint**: Client-users exist with stored least-privilege scope; enforcement deferred to report spec.

## Phase 7: User Story 4 — Per-client report delivery addresses (P2)

**Goal**: Admin stores per-client regular + urgent recipient emails + urgent threshold (storage only).
**Independent test**: Admin sets the three fields; malformed email refused (values unchanged); reviewer forbidden; audited.

- [X] T035 [P] [US4] Integration test report emails in `tests/integration/test_report_emails.py`: set regular/urgent/threshold; malformed email → 400 unchanged; reviewer/client-user → 403; audited.
- [X] T036 [US4] Add `ReportEmailUpdate` schema (`EmailStr` fields, single each) + `set_report_emails` service in `app/clients/schemas.py` / `app/clients/service.py` (FR-017/FR-018).
- [X] T037 [US4] Add `PATCH /clients/{client_id}/report-emails` (`require_admin` + `acting_client`) to `app/clients/routes_clients.py` with `ClientReportEmailChanged` audit.

**Checkpoint**: Report delivery addresses configurable per client; sending deferred to notification spec.

## Phase 8: User Story 5 — Session freshness & tamper-evident audit (P3)

**Goal**: Demotion/deactivation/suspend take effect next request; audit append-only with target attribution.
**Independent test**: Demote a signed-in admin → next request reflects it; suspend a client → its
client-user's next request refused; audit entries immutable and name actor + target client.

- [X] T038 [P] [US5] Integration test session freshness in `tests/integration/test_session_freshness.py`: role/active/client-status change effective on next request without re-login; ~8h token TTL.
- [X] T039 [P] [US5] Integration test audit in `tests/integration/test_audit_append_only.py`: each sensitive write → exactly one entry naming actor + `target_client_id`; no update/delete path mutates audit.
- [X] T040 [US5] Audit-wire all routes: ensure every staff/client-user route (incl. the Phase-4 migrated ones) uses `current_active_principal` + `acting_client`, and that all sensitive writes dispatch their events; fix any gaps found by T038/T039.

## Phase 9: Polish & Cross-Cutting

- [X] T041 [P] Integration test migration in `tests/integration/test_migration_0005.py`: up/down on top of spec-4; dev reset clears users + dependent rows with no dangling FK; documents/watchlists preserved; `ensure_manager` creates exactly one manager and no duplicate on re-run (idempotent).
- [X] T042 [P] Add a small test that the bootstrap manager can change its password after first login (FR-024) in `tests/integration/test_staff_accounts.py` (or a dedicated test).
- [X] T043 [P] Update `memory/spec-breakdown-plan.md` (spec-4b status) and confirm no `ci.yml` change is needed (optional bootstrap secrets, `_REQUIRED_SECRETS` unchanged).
- [X] T044 Run `uv run ruff check app tests` AND `uv run black --check app worker tests`; fix all findings (BOTH must pass); confirm coverage ≥95% auth/account-write, ≥80% overall.
- [ ] T045 Execute the [quickstart.md](./quickstart.md) scenarios on the live stack (migration up/down + a real login/manager/admin/client-user flow + cross-client watchlist deactivation) and record results.

---

## Dependencies & Execution Order

- **Setup (T001–T002)** → **Foundational (T003–T011)** block everything.
- **Foundational order**: enums (T002) → models (T003,T004) → migration schema (T005) → migration data reset (T006); bootstrap (T007)→lifespan (T008); events (T009)→audit handler (T010); guards (T011). Manager seeding lives ONLY in T007/T008 (C2).
- **Phase 3 (US1)** and **Phase 4 (route migration)** both depend only on Foundational and may run in parallel. **Phase 4 is required before the existing app works for staff** and before US2/US4 operate on real client data.
- **User stories** then proceed and are independently testable:
  - **US1 (T012–T019)** — Foundational only. **MVP.**
  - **US2 (T025–T028)** — Foundational (uses seeded manager + acting-client).
  - **US3 (T029–T034)** — Foundational + a client existing (US2 or seeded).
  - **US4 (T035–T037)** — a client existing (US2).
  - **US5 (T038–T040)** — hardens/verifies all prior route paths (incl. Phase 4).
- **Polish (T041–T045)** last.

## Parallel Execution Examples

- **Setup**: T001 ∥ T002.
- **Foundational**: T003 ∥ T004; then T007 ∥ T009 ∥ T010.
- **Per story, tests first in parallel**: US1 → T012 ∥ T013 ∥ T014; Phase 4 test T020 ∥ US1 work; US3 → T029 ∥ T030.
- **Cross-phase `[P]` tests**: T020, T025, T035, T038, T039, T041, T042 (distinct files).

## Implementation Strategy

1. **MVP (Phases 1–3)**: Setup + Foundational + US1 → a working agency identity layer (manager
   administers cross-client, audited staff). Demonstrable on its own.
2. **Make the existing app whole (Phase 4)**: migrate spec-3/4 routes to the acting-client model so
   staff (and client-users) use watchlists/ingestion/documents correctly; add watchlist (de)activation.
3. **Increment**: US2 (client lifecycle) → US3 (client-users+scope) → US4 (report emails) → US5
   (freshness/audit hardening).
4. **PR slicing (<400 lines each, Principle VII)**: PR-A = Setup+Foundational+US1; PR-B = Phase 4 route
   migration; PR-C = US2; PR-D = US3; PR-E = US4+US5; Polish folded into the relevant PR. Run ruff+black
   per PR.
