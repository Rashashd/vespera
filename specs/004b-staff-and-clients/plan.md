# Implementation Plan: Staff & Client Account Model (Agency Foundation Revision)

**Branch**: `004b-staff-and-clients` | **Date**: 2026-06-09 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/004b-staff-and-clients/spec.md`

## Summary

Convert Pantera's identity/authorization layer from per-client multi-tenant SaaS (spec 1–2) into an
internal **agency/CRO** model. Add a `user_type` (`staff` | `client`) distinct from `role`; staff
(`manager`/`admin`/`reviewer`) act **across all clients** with no home `client_id`, while client-side
users stay bound to one client and are visibility-scoped by severity floor and/or watchlist set
(stored now, enforced later). A **manager** owns the client lifecycle (create / soft-delete via the
existing `clients.status` / reactivate) and all staff accounts; an **admin** manages client-users and
per-client report recipient emails; a **reviewer** gets a cross-client report approve/edit permission
(consumed later). The compensating controls that replace the removed `client_id == user.client_id`
wall: every staff action **names a target client** (validated, audited as `target_client_id`),
authorization is **re-read from the DB each request** (fast revocation), the audit log stays
**append-only**, and **client-users remain strictly isolated**. Delivered as one Alembic migration
(`0005`) that performs a **dev reset** (clears users + their FK-dependent rows, seeds one idempotent
bootstrap manager) plus additive columns. Backend/API only. **No new runtime dependency; no new
required Vault secret.**

## Technical Context

**Language/Version**: Python 3.13 (managed by `uv`)

**Primary Dependencies**: FastAPI, fastapi-users (JWT bearer), SQLAlchemy 2 (async), Alembic,
Pydantic v2, `hvac` (Vault, reused), `structlog`. **No new runtime dependency.**

**Storage**: PostgreSQL (existing). Schema changes — `users`: add `user_type`, `client_scope`,
`min_severity`; make `client_id` nullable; expand `ck_users_role`; add a staff/client integrity
CHECK. `clients`: add `report_email_regular`, `report_email_urgent`, `urgent_severity_threshold`
(lifecycle reuses existing `status`). New table `user_watchlist_scope`. One migration `0005`
(down_revision `0004`) with a data reset + idempotent bootstrap-manager seed.

**Testing**: `uv run pytest` (unit + integration). Integration needs `PANTERA_INTEGRATION=1` + the
live stack. Auth/account-write paths targeted at ≥95% line coverage; overall ≥80% (CI gate).

**Target Platform**: Linux container (the `api` service in the existing docker-compose monolith).

**Project Type**: Web service (modular monolith) — backend only this spec.

**Performance Goals**: Not throughput-bound. CRUD + auth; the only NFR is the **~8-hour access-token
lifetime** (config `auth_token_ttl_seconds`: 1800 → 28800) and per-request DB authorization re-check
(already the fastapi-users behavior; extended with a client-active check for client-users).

**Constraints**: Async throughout; Pydantic at the boundary (no ORM leakage); small enums as
`String` + CHECK mirrored by `StrEnum` (spec-3 pattern); `structlog` with no PII/secret in logs;
files ≤ ~300 lines with a one-sentence docstring; never accept `user_type`/`client_id` from a request
body.

**Scale/Scope**: Small. Tens of clients, low hundreds of users; no volume concerns.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Relevance | Status |
|-----------|-----------|--------|
| I. Human-in-the-Loop | No drafting/sending; reviewer approve/edit is permission-only here | ✅ N/A |
| II. Grounding | No reports/claims here | ✅ N/A |
| III. Triage Fails Safe | No triage; client-user empty scope = **default-deny** (least-privilege) aligns with fail-safe bias | ✅ Aligned |
| IV. Backed by a Number | No model/eval; 95% auth-write + 80% overall coverage gates apply; SC-001..011 are the asserted numbers | ✅ Aligned |
| V. Multi-Tenant Isolation (NON-NEGOTIABLE) | **Reframed & ratified** in constitution 1.2.0 (operator exception) — see note | ✅ Ratified |
| VI. Lean, Reproducible, Justified | No new runtime dep; no new container; one package-local change + one migration; no new **required** secret | ✅ Aligned |
| VII. Own Every Line (Spec-Driven) | spec → clarify ×2 → checklist → plan → tasks → implement; Conventional Commits; PR < 400 lines (may split staff/client-user/lifecycle PRs) | ✅ Aligned |

**Principle V reframing (the one deliberate reinterpretation).** Principle V guarantees one client's
data never appears in **another client's** report/retrieval context. That guarantee is upheld in full
for **client-side users**, who remain strictly isolated to their own client and scope (FR-022, FR-007,
SC-009). Internal **staff** are Pantera *operators*, not a competing tenant; their cross-client reach
is a deliberate, **audited** operator capability, not tenant leakage. Compensating controls replace the
removed per-row wall: (a) every staff action names a validated **target client** recorded in the audit
trail; (b) authorization is re-read from current DB state each request; (c) the audit log is
append-only even for the manager superuser; (d) client-users get a strict own-client + least-privilege
(default-deny) scope. **Governance: DONE** — the constitution was amended to **1.2.0** (2026-06-09)
ratifying the internal-operator exception under these four mandatory controls (Principle V). No longer
a pending deviation; the design conforms to the amended principle.

**Engineering standards applied**: async routes/guards; Pydantic schemas at the boundary; `StrEnum` +
CHECK enums; race-safe writes via `INSERT … ON CONFLICT` where concurrent (scope links); audit rows
written in the same transaction via the dispatcher; `structlog` binds actor/target client; bootstrap
credential read from Vault into memory only (never logged/written).

**Result**: PASS — one justified reinterpretation (Principle V), recorded in Complexity Tracking; no
hard violation.

## Project Structure

### Documentation (this feature)

```text
specs/004b-staff-and-clients/
├── plan.md              # This file
├── research.md          # Phase 0 decisions (D1–D12)
├── data-model.md        # Phase 1 tables/enums/relationships
├── quickstart.md        # Phase 1 run/validate guide
├── contracts/           # Phase 1 endpoint + internal contracts
│   ├── staff-accounts.md    # manager: staff CRUD (cross-client)
│   ├── client-lifecycle.md  # manager: client create/suspend/reactivate; admin: report emails
│   ├── client-users.md      # admin: client-user CRUD + severity/watchlist scope
│   └── authz-model.md       # user_type/role matrix, acting-client context, freshness rules
└── checklists/
    ├── requirements.md      # spec-quality gate (passing)
    └── security.md          # security requirements-quality (release gate)
```

### Source Code (repository root)

Additive/edited within the existing `app/auth/` and `app/clients/` packages plus one migration. No new
package, no new container.

```text
app/
├── auth/
│   ├── models.py             # MODIFY: +user_type, +client_scope, +min_severity; client_id nullable;
│   │                         #   integrity CHECK; relationship → UserWatchlistScope
│   ├── schemas.py            # MODIFY: Role += MANAGER, CLIENT_USER; +UserType enum; staff/client schemas
│   ├── dependencies.py       # MODIFY: require_manager/require_staff/require_admin (cross-client);
│   │                         #   acting-client dependency; client-active freshness wrapper
│   ├── backend.py            # (token TTL comes from settings — see config)
│   ├── manager.py            # MODIFY: last-manager guard helper; password policy reused
│   ├── routes_staff.py       # NEW: manager-only staff account CRUD (cross-client)
│   ├── routes_users.py       # REPLACE scope: client-scoped admin user mgmt → client-user mgmt moves
│   │                         #   to clients/routes_client_users.py; legacy client-scoped paths removed
│   └── bootstrap.py          # NEW: idempotent bootstrap-manager seed (create only if no active manager)
├── clients/
│   ├── models.py             # MODIFY: Client += report_email_regular/urgent + urgent_severity_threshold;
│   │                         #   NEW UserWatchlistScope model (or in auth/models.py — see research D6)
│   ├── routes_clients.py     # MODIFY: manager create/suspend/reactivate; admin set report emails;
│   │                         #   all-staff list/read roster
│   ├── routes_client_users.py# NEW: admin creates/scopes client-users for a named client
│   ├── schemas.py            # MODIFY: client create/lifecycle + report-email schemas
│   └── service.py            # MODIFY: lifecycle (status), report-email writes, scope writes (race-safe)
├── core/
│   ├── config.py             # MODIFY: auth_token_ttl_seconds 1800→28800; +bootstrap_manager_email/
│   │                         #   password (OPTIONAL, not in _REQUIRED_SECRETS — no ci.yml change)
│   └── lifespan.py           # MODIFY: call bootstrap.ensure_manager() at startup (idempotent safety net)
├── domain/events.py          # ADD: ClientReactivated, ClientReportEmailChanged, ClientUserCreated,
│   │                         #   ClientUserScopeChanged, ManagerCreated (or reuse UserCreated+role)
├── audit/handler.py          # MODIFY: persist target_client_id for cross-client events
├── db/migrations/versions/
│   └── 0005_staff_and_clients.py  # NEW: schema + dev reset + bootstrap seed (down_revision 0004)
└── main.py                   # MODIFY: register routes_staff, routes_client_users; keep others

tests/
├── unit/
│   ├── test_authz_matrix.py        # role × user_type × action permission table (pure-ish)
│   └── test_scope_rules.py         # empty-scope default-deny; cross-client watchlist refusal
└── integration/
    ├── test_staff_accounts.py      # manager creates staff; last-manager guard; no admin self-escalation
    ├── test_acting_client.py       # staff names target client; missing/inactive/other → refused; audit target
    ├── test_client_lifecycle.py    # create/suspend(freeze)/reactivate; preserve data; no hard delete
    ├── test_client_users.py        # create + scope; explicit-scope; cross-client watchlist refusal
    ├── test_report_emails.py       # set regular/urgent + threshold; malformed refused; reviewer forbidden
    ├── test_session_freshness.py   # demotion/deactivation/suspend effective next request; ~8h TTL
    ├── test_audit_append_only.py   # sensitive writes audited w/ target_client; immutable
    └── test_migration_0005.py      # up/down; dev reset; idempotent bootstrap (no dup manager)
```

**Structure Decision**: Stay inside the existing `auth/` and `clients/` packages (no new package),
matching spec-2/3 layout: thin routers delegating to `service.py`, enums as `StrEnum`+CHECK, one
additive Alembic migration. Split delivery across PRs (staff model+migration → client lifecycle →
client-users+scope → freshness/audit) to keep each < 400 lines.

## Complexity Tracking

| Violation / Deviation | Why Needed | Simpler Alternative Rejected Because |
|-----------------------|------------|--------------------------------------|
| Principle V operator exception (staff cross-client) — **ratified in constitution 1.2.0** | The product is an agency/CRO; staff must operate across all clients to do the work | Keeping strict per-user isolation would make the actual business impossible; client-user isolation is preserved and staff access is audited, so the principle's intent (no cross-**tenant** leakage) holds. Now an approved exception, not a deviation. |
| Migration deletes audit rows authored by wiped users | Wiping users leaves dangling FKs; dev system has only seed data | Nulling FKs/keeping orphaned audit actors adds nullable FKs and confusing orphan rows for zero real benefit pre-launch; FR-020 immutability is a runtime rule, not a migration constraint |
