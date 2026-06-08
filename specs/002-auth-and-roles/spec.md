# Feature Specification: Authentication & Roles

**Feature Branch**: `002-auth-and-roles`

**Created**: 2026-06-06

**Status**: Draft

**Input**: User description: "auth-and-roles — fastapi-users JWT, admin/reviewer roles, role guards, slowapi rate limiting (spec 2 of the Pantera 13-spec build order)"

## Clarifications

### Session 2026-06-06

- Q: What access-token lifetime / refresh strategy should auth use? → A: Short-lived stateless access token (~30 min), no refresh token; users re-authenticate on expiry. Deactivation takes effect within at most one token lifetime.
- Q: How should the very first admin be created (bootstrap, when no users exist)? → A: A one-time operator-run seed script under `scripts/` that reads the initial admin credential from Vault and inserts the admin; no public bootstrap surface.
- Q: What login rate-limit threshold should SC-004 be tested against? → A: 5 attempts per minute per source IP (matches the spec-1 `5/minute` capability).
- Q: Should the audit log gain a foreign key to the new users table for human actors? → A: Yes — add a nullable foreign key to `users.id` for human-originated events; the system sentinel actor (id 0) stays unlinked.
- Q: What is the uniqueness scope for a user's email (the login identifier)? → A: Globally unique across the platform; login by email alone resolves to exactly one user/client.
- Q: Beyond per-IP rate limiting, should the system lock an individual account after repeated failed logins? → A: No — rely on the per-IP rate limit only; no per-account lockout in this spec (avoids an account-lockout denial-of-service vector).
- Q: What minimum password policy should the spec require? → A: Minimum 8 characters including at least one uppercase letter, one lowercase letter, one digit, and one symbol.

## User Scenarios & Testing *(mandatory)*

Pantera is a regulated B2B pharmacovigilance platform. Until now (spec 1) the API had no notion of *who* is calling it. This feature establishes identity: every protected action is performed by a known, authenticated person who holds a specific role within a specific client (tenant). The two roles are **admin** (manages users and configuration) and **reviewer** (the only role authorized to approve a safety report for delivery, per the constitution's Human-in-the-Loop principle). This spec does not build the approval flow itself — it builds the identity and authorization foundation every later spec depends on.

### User Story 1 - Authenticate and obtain a session (Priority: P1)

A registered user submits their credentials and receives a time-limited access token that proves their identity on subsequent requests. Without a valid token, protected endpoints reject the request.

**Why this priority**: Nothing else in the platform can be access-controlled until a caller can prove who they are. This is the irreducible MVP — it is the foundation every other story and every later spec builds on.

**Independent Test**: Create a user, log in with correct credentials, receive a token, call a protected endpoint successfully with the token, and confirm the same endpoint is rejected without (or with an invalid/expired) token.

**Acceptance Scenarios**:

1. **Given** a registered active user, **When** they submit correct credentials, **Then** they receive a valid access token and can call a protected endpoint.
2. **Given** a registered user, **When** they submit an incorrect password, **Then** authentication is refused with a generic failure message that does not reveal whether the email exists.
3. **Given** a protected endpoint, **When** it is called with no token, an expired token, or a tampered token, **Then** the request is rejected as unauthenticated.
4. **Given** a user whose account has been deactivated, **When** they attempt to authenticate, **Then** authentication is refused.

---

### User Story 2 - Enforce role-based authorization (Priority: P1)

An authenticated user attempts an action. The system permits it only if the user holds the role that action requires. An admin-only action is refused for a reviewer, and a reviewer-only action (e.g., authorizing a send, in a later spec) is refused for anyone who is not a reviewer.

**Why this priority**: Authentication without authorization is meaningless for a regulated system — the constitution requires that only a `reviewer` can authorize delivery. Role guards are the reusable mechanism every later spec calls to protect its endpoints, so they must ship alongside authentication.

**Independent Test**: Create one admin and one reviewer; protect a test endpoint with an admin-only guard and another with a reviewer-only guard; confirm each role is allowed through its own guard and refused by the other.

**Acceptance Scenarios**:

1. **Given** an authenticated admin, **When** they call an admin-only endpoint, **Then** the request succeeds.
2. **Given** an authenticated reviewer, **When** they call an admin-only endpoint, **Then** the request is refused as forbidden (authenticated but not authorized).
3. **Given** an authenticated reviewer, **When** they call a reviewer-only endpoint, **Then** the request succeeds.
4. **Given** an authenticated admin, **When** they call a reviewer-only endpoint, **Then** the request is refused as forbidden.
5. **Given** an unauthenticated caller, **When** they call any role-guarded endpoint, **Then** the request is refused as unauthenticated (before any role check).

---

### User Story 3 - Administer users within a client (Priority: P2)

An admin creates user accounts for their organization, assigns each a role (admin or reviewer), and deactivates accounts that should no longer have access. New users belong to the admin's own client (tenant) and cannot see or affect users of any other client.

**Why this priority**: The platform needs a way to populate and maintain its user base, but the system is already demonstrable for the auth/authorization MVP with seeded users (P1 stories). Admin user management is the next layer of value and the realistic operational path, so it is P2 rather than P1.

**Independent Test**: As an admin, create a reviewer account scoped to the admin's client, log in as that new reviewer, then deactivate it as the admin and confirm the reviewer can no longer authenticate — all while a second client's users remain unaffected.

**Acceptance Scenarios**:

1. **Given** an authenticated admin, **When** they create a user with a role and an initial credential, **Then** the new user belongs to the admin's client and can authenticate.
2. **Given** an authenticated admin, **When** they list users, **Then** they see only users belonging to their own client.
3. **Given** an authenticated admin, **When** they deactivate a user, **Then** that user can no longer authenticate, but existing data attributed to that user is preserved.
4. **Given** a reviewer (non-admin), **When** they attempt any user-management action, **Then** the request is refused as forbidden.
5. **Given** an admin of client A, **When** they attempt to view or modify a user of client B, **Then** the request is refused and no client B data is revealed.

---

### User Story 4 - Resist brute-force and credential-stuffing on login (Priority: P2)

Repeated authentication attempts from the same source are throttled so that automated password-guessing and credential-stuffing attacks are slowed to an ineffective rate, while legitimate users who mistype occasionally are not meaningfully impacted.

**Why this priority**: The constitution mandates rate-limited auth endpoints. It is a security hardening layer on top of working authentication (P1), so it is P2 — valuable and required for production, but the auth MVP is demonstrable without it.

**Independent Test**: Issue login attempts in rapid succession beyond the configured threshold and confirm further attempts within the window are throttled with a clear "too many requests" response, then confirm attempts succeed again after the window resets.

**Acceptance Scenarios**:

1. **Given** the login endpoint, **When** a single source exceeds the allowed number of attempts within the time window, **Then** further attempts in that window are rejected with a rate-limit response.
2. **Given** a source that was throttled, **When** the time window elapses, **Then** the source may attempt to authenticate again.
3. **Given** rate limiting is active, **When** a legitimate user authenticates within the allowed attempt budget, **Then** they are not impeded.

---

### Edge Cases

- **No users exist yet**: The system must provide a defined way to obtain the first admin (seed/bootstrap), since user creation otherwise requires an existing admin.
- **Duplicate identity**: Email is unique across the entire platform; attempting to create a user with an email already in use (under any client) is rejected with a clear, non-leaking error.
- **Token lifecycle**: An access token presented after expiry is treated as unauthenticated; a malformed or signature-invalid token is rejected without revealing why in detail.
- **Self-deactivation / last admin**: An admin attempting to deactivate themselves or the last remaining admin of a client must not be able to lock the client out of administration.
- **Role escalation attempt**: A non-admin must not be able to change their own (or anyone's) role.
- **Audit continuity**: The audit log introduced in spec 1 uses a sentinel system actor (id 0). Introducing real human users must not break audit logging for system-originated events, and human-originated security events must be attributable to the acting user.
- **Cross-tenant token reuse**: A valid token for client A must never grant access to client B's resources.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST allow a registered, active user to authenticate with email + password and receive a short-lived (~30 minute) stateless bearer access token; there is no refresh token, so a user re-authenticates after expiry. Consequently, deactivating a user takes effect within at most one token lifetime.
- **FR-002**: System MUST reject authentication for incorrect credentials and for deactivated accounts, using a generic failure response that does not disclose whether a given email is registered.
- **FR-003**: System MUST reject any request to a protected endpoint that lacks a valid, unexpired, untampered token, treating it as unauthenticated.
- **FR-004**: System MUST support exactly two roles — `admin` and `reviewer` — and store each user's role as part of their account.
- **FR-005**: System MUST provide reusable authorization guards that protect an endpoint by required role, returning a "forbidden" outcome (distinct from "unauthenticated") when an authenticated user lacks the required role.
- **FR-006**: System MUST enforce that only an `admin` can create users, assign or change roles, and deactivate users.
- **FR-007**: System MUST scope every user to a single client (tenant), and all user-management and listing operations MUST be restricted to the acting admin's own client; no operation may read or modify another client's users. A user's email MUST be unique across the entire platform (global uniqueness), so authentication by email alone resolves to exactly one user and client.
- **FR-008**: System MUST allow an admin to deactivate a user such that the user can no longer authenticate, while preserving historical data and audit records attributed to that user.
- **FR-009**: System MUST store passwords only in a securely hashed form and MUST never log, return, or otherwise expose raw passwords or password hashes.
- **FR-010**: System MUST rate-limit authentication attempts to 5 attempts per minute per source IP, returning a clear rate-limit response when the threshold is exceeded and resuming after the window resets, to throttle brute-force and credential-stuffing. The system MUST NOT lock individual accounts after repeated failed logins (per-IP throttling only), to avoid an account-lockout denial-of-service vector.
- **FR-011**: System MUST provide a one-time, operator-run seed script (under `scripts/`) that creates the initial admin when no users exist, reading the initial admin credential from Vault. There MUST be no publicly reachable bootstrap endpoint, and the admin-only constraint for ongoing user creation MUST remain in force.
- **FR-012**: System MUST record security-relevant events (successful login, failed login, user created, role changed, user deactivated) to the existing audit log, attributing human-originated events to the acting user via a nullable foreign key to `users.id`, while the system sentinel actor (id 0) remains unlinked and available for system-originated events.
- **FR-013**: System MUST prevent an action that would leave a client with no active admin (e.g., deactivating or demoting the last admin).
- **FR-014**: System MUST forbid privilege escalation: a non-admin cannot alter any user's role, including their own.
- **FR-015**: Authentication and authorization signing material and related secrets MUST be sourced from the platform secret store (Vault), never from a local environment file or committed configuration.
- **FR-016**: System MUST enforce a minimum password policy of at least 8 characters including at least one uppercase letter, one lowercase letter, one digit, and one symbol, rejecting non-conforming passwords at account creation and password change with a clear validation message.

### Key Entities *(include if feature involves data)*

- **User**: A person who can authenticate. Key attributes: globally-unique email (identity), securely hashed credential, role (`admin` or `reviewer`), active/inactive status, and the client (tenant) they belong to. Relates to Client (belongs to one) and to audit events (is the actor of human-originated security events).
- **Role**: The authorization level a user holds — `admin` (manages users/config) or `reviewer` (authorized to approve sends in later specs). Determines which guarded actions a user may perform.
- **Client (Tenant)**: The organizational boundary established in spec 1; every user belongs to exactly one client, and authorization decisions and data visibility are scoped to it.
- **Session / Access Token**: A short-lived (~30 minute), stateless credential issued on successful authentication that conveys the caller's identity, role, and client on subsequent requests. No refresh token is issued; expiry requires re-authentication.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of protected endpoints reject requests that present no token, an expired token, or a tampered token.
- **SC-002**: For every role-guarded action, a user holding the required role is permitted and a user lacking it is refused — verified across both roles with zero incorrect allows or denies.
- **SC-003**: No request authenticated for one client can read or modify any other client's users or data — zero cross-tenant access in testing.
- **SC-004**: Authentication endpoints throttle a single source IP to no more than 5 attempts per minute; the 6th attempt within the window is rejected with a rate-limit response, while legitimate within-budget logins always succeed and the source may retry after the window resets.
- **SC-005**: Raw passwords and password hashes never appear in any log, API response, trace, or stored summary — verified by inspection of outputs across all auth flows.
- **SC-006**: Every security-relevant event (login success/failure, user created, role changed, user deactivated) produces exactly one corresponding audit-log entry attributed to the correct actor.
- **SC-007**: The auth and user-write code paths meet the constitution's elevated coverage bar (95%+ line coverage on auth and database-write paths), and the overall suite stays at or above the 80% gate.
- **SC-008**: A client can never be left without an active admin; every attempt to remove the last admin is blocked.

## Assumptions

- **Identity model**: Users authenticate with email + password and receive a bearer access token (standard for B2B SaaS APIs). Federated SSO/OAuth and multi-factor authentication are out of scope for this spec and may be layered later.
- **Token strategy**: Stateless ~30-minute access tokens are used, with no refresh token (users re-authenticate on expiry). "Remember me" and full session revocation lists are out of scope; deactivation prevents *new* authentications and takes effect within at most one token lifetime for already-issued tokens.
- **Two roles only**: The platform requires exactly `admin` and `reviewer` for the foreseeable specs; finer-grained permissions are out of scope. The reviewer's send-authorization power is *declared* here but *exercised* in the later HITL/approval spec.
- **Tenant model reused**: The `client_id` tenant boundary and the audit-log infrastructure from spec 1 are reused; this spec adds the `users` table and a nullable foreign key from the audit log to `users.id` for human actors, which must not break the existing system-actor sentinel (id 0).
- **Reuse of existing rate-limit capability**: A Redis-backed rate-limiting capability already exists from spec 1; this spec contributes the *policy* applied to the login route, not new infrastructure.
- **Secrets in Vault**: All auth secrets (e.g., token signing material) are written to and read from Vault via the established secret-loading path; nothing auth-related is stored in a local environment file.
- **Self-service registration is disabled**: In a B2B regulated context, accounts are provisioned by an admin (or the bootstrap path); there is no public open sign-up.
- **Password policy**: Passwords MUST be at least 8 characters and include at least one uppercase letter, one lowercase letter, one digit, and one symbol; industry-standard hashing is applied. (Hashing algorithm/cost parameters remain an implementation detail for planning.)
