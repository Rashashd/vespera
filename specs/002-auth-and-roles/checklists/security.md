# Security & Authorization Checklist: Authentication & Roles

**Purpose**: Validate the *quality* of the security & authorization requirements (completeness, clarity, consistency, measurability, coverage) before planning — a formal release-gate review of the requirements themselves, not the implementation.
**Created**: 2026-06-06
**Feature**: [spec.md](../spec.md)
**Depth**: Formal release gate · **Audience**: Reviewer / release gate

## Authentication Requirements

- [ ] CHK001 Is the authentication credential type (email + password) explicitly specified, with federated/SSO and MFA stated as out of scope? [Completeness, Spec §FR-001 / Assumptions]
- [ ] CHK002 Is the access-token lifetime quantified (not a vague "short-lived") with a concrete value? [Clarity, Spec §FR-001]
- [ ] CHK003 Are the consequences of the no-refresh-token decision (re-auth on expiry; deactivation latency ≤ one token lifetime) stated as requirements rather than left implicit? [Completeness, Spec §FR-001 / Clarifications]
- [ ] CHK004 Are requirements defined for rejecting absent, expired, and tampered/invalid-signature tokens as *distinct* but uniformly-unauthenticated cases? [Coverage, Spec §FR-003 / Edge Cases]
- [ ] CHK005 Is the requirement for a generic, non-enumerating failure response on bad credentials measurable (i.e., defines that it must not reveal whether an email exists)? [Measurability, Spec §FR-002]

## Authorization & Role Requirements

- [ ] CHK006 Are exactly the two roles (`admin`, `reviewer`) enumerated, with no ambiguity about additional/implicit roles? [Clarity, Spec §FR-004]
- [ ] CHK007 Is the distinction between "unauthenticated" (no/invalid token) and "forbidden" (authenticated, wrong role) defined as a requirement, not just an acceptance scenario? [Completeness, Spec §FR-005 / US2]
- [ ] CHK008 Are role-guard requirements stated as reusable across endpoints (so later specs inherit them) rather than scoped to one route? [Clarity, Spec §FR-005]
- [ ] CHK009 Is the reviewer's exclusive send-authorization authority declared here and explicitly deferred to the later HITL spec, with no conflicting "send" requirement in this spec? [Consistency, Spec §Assumptions / Constitution I]
- [ ] CHK010 Are anti-privilege-escalation requirements complete (no non-admin may change any role, including their own)? [Coverage, Spec §FR-014]

## Multi-Tenant Isolation Requirements

- [ ] CHK011 Is every user required to belong to exactly one client (tenant), with no unscoped/global user state left undefined? [Completeness, Spec §FR-007]
- [ ] CHK012 Are all user-management and listing operations explicitly required to be client-scoped, with cross-client read AND modify both forbidden? [Coverage, Spec §FR-007 / US3]
- [ ] CHK013 Is a cross-tenant token-reuse refusal requirement present (a valid token for client A must never reach client B data)? [Coverage, Spec §Edge Cases / SC-003]
- [ ] CHK014 Is the email-uniqueness scope unambiguously stated as global (resolving login to one user/client), with the earlier "within the same scope" wording removed? [Consistency, Spec §FR-007 / Clarifications]
- [ ] CHK015 Is "zero cross-tenant access" expressed as an objectively verifiable outcome? [Measurability, Spec §SC-003]

## Secrets & Data Protection Requirements

- [ ] CHK016 Is the requirement that auth secrets (token signing material) come only from Vault — never `.env`/committed config — stated explicitly? [Completeness, Spec §FR-015 / Constitution Security]
- [ ] CHK017 Is secure password hashing required, with raw passwords and hashes forbidden from logs, responses, traces, and stored summaries? [Coverage, Spec §FR-009 / SC-005]
- [x] CHK018 Is the password-strength policy either specified or explicitly flagged as a deferred planning decision (so its absence is intentional, not an oversight)? [Resolved — Spec §FR-016: min 8 chars + upper/lower/digit/symbol]
- [ ] CHK019 Can "passwords/hashes never appear in any output" be objectively verified across all auth flows? [Measurability, Spec §SC-005]

## Rate Limiting & Abuse Resistance Requirements

- [ ] CHK020 Is the rate-limit threshold quantified with a number, window, and keying dimension (5/min per source IP)? [Clarity, Spec §FR-010 / SC-004]
- [ ] CHK021 Is the deliberate exclusion of per-account lockout stated as a requirement, with its rationale (lockout-DoS avoidance) recorded? [Completeness, Spec §FR-010 / Clarifications]
- [ ] CHK022 Are the throttle boundaries (Nth attempt rejected, retry-after-window-reset, legitimate within-budget always succeeds) expressed as testable acceptance criteria? [Measurability, Spec §SC-004 / US4]
- [ ] CHK023 Is the relationship to the reused spec-1 rate-limit capability described as policy-only (no new infra), avoiding a hidden implementation dependency in requirements? [Consistency, Spec §Assumptions]

## Lifecycle & Edge-Case Coverage

- [ ] CHK024 Are bootstrap requirements (operator seed script, Vault-sourced credential, no public endpoint) complete and consistent with the admin-only constraint? [Coverage, Spec §FR-011 / Edge Cases]
- [ ] CHK025 Is the last-admin / self-deactivation lockout-prevention requirement defined so a client can never be left without an active admin? [Coverage, Spec §FR-013 / SC-008]
- [ ] CHK026 Is the deactivation requirement clear that it blocks future auth while preserving historical data and audit attribution? [Clarity, Spec §FR-008 / Edge Cases]
- [ ] CHK027 Is duplicate-identity handling specified with a clear, non-leaking error given global email uniqueness? [Edge Case, Spec §Edge Cases]
- [ ] CHK028 Are there requirements for the "no users exist yet" state beyond bootstrap (e.g., protected endpoints still refuse all callers)? [Coverage, Spec §Edge Cases]

## Audit & Compliance Requirements

- [ ] CHK029 Is the set of audited security events enumerated (login success/failure, user created, role changed, user deactivated) with no obvious gaps? [Completeness, Spec §FR-012]
- [ ] CHK030 Is human-actor attribution via a nullable FK to `users.id` specified without breaking the spec-1 system sentinel (id 0)? [Consistency, Spec §FR-012 / Clarifications]
- [ ] CHK031 Is "exactly one audit entry per security event, attributed to the correct actor" stated as an objectively measurable outcome? [Measurability, Spec §SC-006]
- [ ] CHK032 Are the elevated coverage obligations (95%+ on auth and DB-write paths; ≥80% overall) captured as explicit, verifiable success criteria? [Measurability, Spec §SC-007 / Constitution]

## Consistency, Dependencies & Assumptions

- [ ] CHK033 Do the Clarifications decisions (token lifetime, bootstrap, rate limit, audit FK, email scope, lockout) each have a matching, non-contradictory requirement in the body? [Consistency, Spec §Clarifications]
- [ ] CHK034 Are the spec-1 dependencies (client_id boundary, audit-log infra, Redis rate-limit capability, Vault secret loading) documented as validated assumptions rather than unstated preconditions? [Assumption, Spec §Assumptions]
- [ ] CHK035 Is self-service registration explicitly excluded so account provisioning is unambiguously admin/bootstrap-only? [Boundary, Spec §Assumptions]
- [ ] CHK036 Are all functional requirements traceable to at least one acceptance scenario or success criterion (no orphan FRs, no unsupported SCs)? [Traceability, Spec §FR / §SC]

## Notes

- This is a requirements-quality gate ("unit tests for English"): each item asks whether the requirement is *well-written*, not whether the system behaves correctly.
- Items marked `[Gap]` flag possibly-missing requirements; `[Ambiguity]`/`[Conflict]` flag wording to resolve before `/speckit-plan`.
- CHK018 (password policy) was resolved via the 2026-06-06 clarification: FR-016 now requires min 8 chars with upper/lower/digit/symbol.
- Check items off as the spec is reviewed/updated; unresolved items should block progression to planning.
