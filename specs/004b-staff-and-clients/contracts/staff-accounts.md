# Contract: Staff Account Management (manager-only, cross-client)

**Feature**: 004b-staff-and-clients · `app/auth/routes_staff.py` · guard `require_manager`.

Staff users have `user_type='staff'`, no `client_id`, `role ∈ {manager,admin,reviewer}`. Only a manager
manages staff (FR-003/FR-004). All actions audited (FR-021).

## POST `/staff` — create a staff user

- Auth: `require_manager`. Body: `{ email, password, role }` (`role` staff-only; `user_type`/`client_id`
  rejected if present, FR-009). Validates password policy (reused) + global email uniqueness (D3).
- 201 → `StaffUserOut { id, email, role, user_type='staff', is_active, created_at }`.
- Errors: 403 non-manager; 409 `USER_ALREADY_EXISTS`; 400 `PASSWORD_POLICY`/`INVALID_EMAIL`/
  `MANAGER_REQUIRED` (only a manager may create a manager — enforced by the guard).
- Audit: `UserCreated` (client_id NULL).

## GET `/staff` — list staff users

- Auth: `require_manager`. Query: `limit`, `offset`. 200 → `list[StaffUserOut]` (all staff, no client
  scoping). (Read of the staff roster is manager-only; admins/reviewers do not manage staff.)

## PATCH `/staff/{user_id}` — change role / active status

- Auth: `require_manager`. Body: `{ role?, is_active? }`. Guards: only a manager may set
  `role='manager'`; the **last active manager** cannot be demoted/deactivated, including self
  (FR-005 → 409 `LAST_MANAGER`); `user_type`/`client_id` immutable (400 `IMMUTABLE_FIELD`).
- 200 → `StaffUserOut`. Audit: `UserRoleChanged` and/or `UserDeactivated`.

## Notes

- Self-service password change (changeable after first login, FR-024) reuses the existing fastapi-users
  password-update path; force-change-on-first-login is the intended hardening (not built here).
- The bootstrap manager is seeded by migration `0005` + the idempotent startup safety net (D8), not via
  this endpoint.
