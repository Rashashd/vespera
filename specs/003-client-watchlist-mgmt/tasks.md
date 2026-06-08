---
description: "Task list for Client & Watchlist Management (spec 3)"
---

# Tasks: Client & Watchlist Management

**Input**: Design documents from `specs/003-client-watchlist-mgmt/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/clients.md, contracts/watchlists.md, quickstart.md

**Tests**: INCLUDED — the constitution mandates testing gates (95% on DB-write paths, 80% overall) and prior specs shipped full suites. Write each test before its implementation and confirm it fails first.

**Organization**: Tasks are grouped by user story (US1–US5) so each can be implemented and tested independently. Paths follow the spec-2 layout: feature package under `app/clients/`, migration under `app/db/migrations/versions/`, tests under `tests/`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no incomplete dependencies)
- **[Story]**: US1–US5 (omitted for Setup/Foundational/Polish)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the feature package skeleton and its enums.

- [X] T001 Create the `app/clients/` package with `app/clients/__init__.py` (one-sentence module docstring) per plan.md structure
- [X] T002 [P] Create `app/clients/enums.py` with `ClientStatus`, `Cadence` (default weekly), `SeverityLevel` (ordered: non-serious<serious<life-threatening, default serious), `WatchlistItemType` as `StrEnum`s (data-model.md §Enums)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared ORM, migration, events, service/route scaffolding that ALL stories depend on.

**⚠️ CRITICAL**: No user-story work begins until this phase completes.

- [X] T003 [P] Create ORM models in `app/clients/models.py` — `Client`, `Watchlist`, `WatchlistItem`, `WatchlistBudgetUsage` (BigInteger PKs, `client_id` columns + indexes, CHECK-constraint enums, unique indexes per data-model.md)
- [X] T004 [P] Add frozen `DomainEvent` subclasses to `app/domain/events.py`: `ClientCreated`, `ClientUpdated`, `ClientSuspended`, `WatchlistCreated`, `WatchlistUpdated`, `WatchlistDeactivated`, `WatchlistItemAdded`, `WatchlistItemRemoved` (research D10; auto-audited by existing handler)
- [X] T005 Create Alembic migration `app/db/migrations/versions/0003_clients_watchlists.py` — create the four tables; reconcile existing `users.client_id` (INSERT distinct → `clients`, ensure bootstrap client id, `setval` sequence), then add FK `users.client_id → clients.id`; reversible `downgrade` (research D5; depends on T003)
- [X] T006 [P] Create `app/clients/service.py` skeleton — client-scoped fetch helpers (cross-tenant→None), current-UTC-month helper, and pure `derive_budget_state(budget, spend)` function (data-model.md derivation)
- [X] T007 [P] Create route skeletons `app/clients/routes_clients.py` (`APIRouter(prefix="/clients")`) and `app/clients/routes_watchlists.py` (`APIRouter(prefix="/watchlists")`) with bare routers + tags
- [X] T008 Register `clients_router` and `watchlists_router` in `app/main.py` (depends on T007)
- [X] T009 [P] Integration test `tests/integration/test_migration_0003.py` — upgrade reconciles all `users.client_id` (no orphans, SC-001), FK enforced, `downgrade -1` clean

**Checkpoint**: Schema + scaffolding ready — user stories can begin.

---

## Phase 3: User Story 1 - Establish a client (tenant) record (Priority: P1) 🎯 MVP

**Goal**: A first-class `clients` record with lifecycle; existing users resolve to real clients.

**Independent Test**: Onboard a client via the operator script, read it via `GET /clients/me`, rename via `PATCH /clients/me`, confirm case-insensitive name uniqueness and that reconciliation left no orphaned `client_id`.

### Tests for User Story 1

- [X] T010 [P] [US1] Integration test `tests/integration/test_clients.py` — seed_client create, `GET /clients/me`, `PATCH /clients/me` rename, duplicate (case-insensitive) name → 409, suspend via script; assert **exactly one** audit row per mutation attributed to the acting actor (SC-008) (contracts/clients.md)
- [X] T011 [P] [US1] Unit test `tests/unit/test_clients_schemas.py` — `ClientRead`/`ClientUpdate` validation (name trim/non-empty; no `status` field accepted)

### Implementation for User Story 1

- [X] T012 [P] [US1] Add `ClientRead`, `ClientUpdate` Pydantic schemas to `app/clients/schemas.py` (no ORM leakage; `status` not settable via API)
- [X] T013 [US1] Add client service methods to `app/clients/service.py` — `get_client(session, client_id)`, `rename_client` (case-insensitive uniqueness → conflict), suspend/activate helpers used by the script (depends on T006)
- [X] T014 [US1] Implement `GET /clients/me` (`current_active_user`) and `PATCH /clients/me` (`require_admin`) in `app/clients/routes_clients.py`, dispatching `ClientUpdated` in-transaction (contracts/clients.md; depends on T012, T013)
- [X] T015 [US1] Create operator script `scripts/seed_client.py` — `--name` create, `--suspend`/`--activate <id>`, emitting `ClientCreated`/`ClientSuspended`/`ClientUpdated` (research D1; mirrors `scripts/seed_admin.py`)

**Checkpoint**: Clients exist, are scoped, audited, and reconciled — MVP demonstrable.

---

## Phase 4: User Story 2 - Define one or more watchlists (Priority: P1)

**Goal**: Named watchlists (1:many per client) holding drugs/MeSH/keywords, client-scoped, idempotent membership, soft-delete.

**Independent Test**: Create two named watchlists with items, reject an empty one and a duplicate name, confirm idempotent item add and cross-tenant invisibility.

### Tests for User Story 2

- [X] T016 [P] [US2] Integration test `tests/integration/test_watchlists.py` — create with items, empty→400, two distinct names, duplicate name→409, list (+include_inactive), get, rename, deactivate (soft-delete), add duplicate item→200 no-op, remove absent item graceful, remove-to-empty→400; assert **exactly one** audit row per mutation (SC-008), and zero rows for idempotent no-ops (contracts/watchlists.md)
- [X] T017 [P] [US2] Integration test `tests/integration/test_clients_authz.py` — admin writes allowed; reviewer GET allowed but writes→403; unauthenticated→401; admin of client A requesting client B watchlist→404 (SC-003, SC-007)

### Implementation for User Story 2

- [X] T018 [P] [US2] Add `WatchlistCreate`, `WatchlistUpdate`, `WatchlistRead`, `WatchlistItem`, `WatchlistItemAdd` schemas to `app/clients/schemas.py`
- [X] T019 [US2] Add watchlist service methods to `app/clients/service.py` — create (≥1 item, in-payload dedup), list (client-scoped), get (cross-tenant→None), rename (per-client uniqueness), deactivate (soft-delete), add_item (idempotent), remove_item (graceful + active-empty guard) (depends on T006, T013)
- [X] T020 [US2] Implement watchlist CRUD routes `POST /watchlists`, `GET /watchlists`, `GET /watchlists/{id}`, `PATCH /watchlists/{id}` in `app/clients/routes_watchlists.py` (depends on T018, T019)
- [X] T021 [US2] Implement item routes `POST /watchlists/{id}/items`, `DELETE /watchlists/{id}/items/{item_id}` in `app/clients/routes_watchlists.py` (depends on T020)
- [X] T022 [US2] Dispatch `WatchlistCreated`/`WatchlistUpdated`/`WatchlistDeactivated`/`WatchlistItemAdded`/`WatchlistItemRemoved` in-transaction from the routes/service (depends on T020, T021)

**Checkpoint**: Clients + watchlists with items work independently and are isolated per tenant.

---

## Phase 5: User Story 3 - Configure monitoring cadence per watchlist (Priority: P2)

**Goal**: Per-watchlist cadence from `{daily, weekly, monthly}`, default `weekly`, validated, independent across watchlists.

**Independent Test**: Set two watchlists of one client to different cadences, confirm default applies when unset and an invalid value is rejected.

### Tests for User Story 3

- [X] T023 [P] [US3] Integration test `tests/integration/test_watchlist_cadence.py` — set cadence per watchlist, default `weekly` when unset, invalid value→422, sibling independence (FR-006)

### Implementation for User Story 3

- [X] T024 [US3] Ensure `cadence` is settable on create and `PATCH /watchlists/{id}`, defaults to `weekly`, and out-of-set values map to 422 in `app/clients/schemas.py` and `app/clients/service.py` (depends on T019, T020)

**Checkpoint**: Cadence configurable and validated per watchlist.

---

## Phase 6: User Story 4 - Configure a severity threshold per watchlist (Priority: P2)

**Goal**: Per-watchlist severity threshold from the three ordered ICH levels, default `serious`, validated. (Custom severity keywords are OUT OF SCOPE — FR-008.)

**Independent Test**: Set a watchlist's threshold to a valid level, confirm default `serious` when unset and an out-of-set value is rejected.

### Tests for User Story 4

- [X] T025 [P] [US4] Integration test `tests/integration/test_watchlist_severity.py` — set `severity_threshold` per watchlist, default `serious` when unset, invalid value→422 (FR-007)

### Implementation for User Story 4

- [X] T026 [US4] Ensure `severity_threshold` is settable on create and `PATCH /watchlists/{id}`, defaults to `serious`, and out-of-set values map to 422 in `app/clients/schemas.py` and `app/clients/service.py` (depends on T019, T020)

**Checkpoint**: Severity threshold configurable and validated per watchlist.

---

## Phase 7: User Story 5 - Set and enforce a monitoring cost budget per watchlist (Priority: P3)

**Goal**: Per-watchlist recurring monthly (UTC) budget with derived warn(80%)→soft-cap(100%) state, sibling isolation, raise-clears, month auto-reset.

**Independent Test**: With a budget set, simulate current-month spend across 80% and 100%, confirm warning then soft-cap, a sibling stays ok, raising the budget clears the cap, and a new UTC month auto-resets.

### Tests for User Story 5

- [X] T027 [P] [US5] Unit test `tests/unit/test_budget_state.py` — pure `derive_budget_state`: null budget→ok, <80%→ok, 80–100%→warning, ≥100%→soft_capped, exact boundaries
- [X] T028 [P] [US5] Integration test `tests/integration/test_watchlist_budget.py` — simulate `watchlist_budget_usage` rows: warning at 80%, soft_capped at 100%, sibling watchlist unaffected (FR-011), raise budget clears (FR-012), new UTC-month period→ok (auto-resume)

### Implementation for User Story 5

- [X] T029 [US5] Add `budget_amount` to create/update schemas (≥0), expose derived `budget_status` + `current_period_spend` in `WatchlistRead`, wire `derive_budget_state` + current-UTC-month usage read (and a `record_spend` helper for tests) in `app/clients/schemas.py` and `app/clients/service.py` (depends on T006, T019, T020)

**Checkpoint**: All five stories independently functional.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [X] T030 [P] Update `docs/RUNBOOK.md` with the `seed_client.py` operator flow and the `/clients`, `/watchlists` endpoints
- [X] T031 [P] Verify one-sentence module docstrings on every new file and that no file exceeds ~300 lines (split `app/clients/routes_watchlists.py` if needed)
- [X] T032 Run `uv run ruff check app worker tests scripts` and `uv run black --check app worker tests scripts`; fix all findings
- [X] T033 Run `PANTERA_INTEGRATION=1 uv run pytest` (full stack up) — confirm green, config-write paths ≥95%, overall ≥80%
- [X] T034 Execute `specs/003-client-watchlist-mgmt/quickstart.md` end-to-end against the live stack

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (P1)**: no dependencies.
- **Foundational (P2)**: depends on Setup; **BLOCKS all user stories**. T005 depends on T003; T008 depends on T007.
- **User Stories (P3–P7)**: all depend on Foundational. US1 and US2 are both P1 (US1 first as MVP). US3/US4/US5 build on US2's watchlist routes/service.
- **Polish (P8)**: depends on all targeted stories complete.

### User Story Dependencies

- **US1 (P1)**: after Foundational; independent.
- **US2 (P1)**: after Foundational; independent of US1 at runtime (shares `schemas.py`/`service.py` files, so order edits, not logic).
- **US3, US4 (P2)**: extend US2's watchlist create/PATCH path (T019/T020) — start after US2.
- **US5 (P3)**: extends US2 + uses the foundational budget-state fn (T006) — start after US2.

### Within Each User Story

- Tests written first and failing → schemas → service → routes → event wiring.
- Same-file tasks (`schemas.py`, `service.py`, `routes_watchlists.py`) run sequentially, not `[P]`.

### Parallel Opportunities

- T002 (enums) ∥ nothing else in Setup.
- Foundational: T003 ∥ T004 ∥ T006 ∥ T007 ∥ T009 (different files); T005 after T003; T008 after T007.
- US1: T010 ∥ T011 (tests); T012 ∥ (schemas) then T013→T014; T015 independent file.
- US2: T016 ∥ T017 (tests); T018 (schemas) before T019→T020→T021→T022.
- US3 ∥ US4 test files (T023, T025) are independent; their impl tasks (T024, T026) touch shared `schemas.py`/`service.py` so serialize those.
- US5: T027 ∥ T028 (tests).
- Polish: T030 ∥ T031.

---

## Parallel Example: User Story 2

```bash
# Tests first (different files):
Task: "Integration test tests/integration/test_watchlists.py"
Task: "Integration test tests/integration/test_clients_authz.py"

# Then implementation in file order (schemas → service → routes → events):
Task: "Add watchlist schemas in app/clients/schemas.py"
# (service, routes, events follow sequentially — same files)
```

---

## Implementation Strategy

### MVP First

1. Phase 1 Setup → Phase 2 Foundational (migration + scaffolding).
2. Phase 3 US1 (clients) → **validate**: clients reconciled, scoped, audited.
3. Phase 4 US2 (watchlists) → **validate**: the core "client + what they watch" MVP.
4. STOP and demo — US1+US2 is a coherent, shippable increment.

### Incremental Delivery

5. Add US3 (cadence) → US4 (severity) → US5 (budget), each independently tested and demoed.
6. Polish: docs, lint/format, full suite + coverage, quickstart validation.

---

## Notes

- `[P]` = different files, no incomplete dependency. `[Story]` maps the task to its user story.
- No new Vault secret and no `ci.yml` change (research D12) — avoids the spec-2 CI secret footgun.
- Commit per task or logical group; Conventional Commits, NO Co-Authored-By trailer.
- Multi-tenant isolation (Constitution V) is exercised explicitly in T017 — keep it green.
