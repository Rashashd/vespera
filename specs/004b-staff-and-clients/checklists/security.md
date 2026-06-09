# Security & Authorization Requirements Quality Checklist: Staff & Client Account Model

**Purpose**: Release-gate validation of the *requirements themselves* (completeness, clarity,
consistency, measurability, coverage) for the agency foundation revision — authorization & privilege
model, multi-tenant isolation reframing, migration/data-integrity, auditability, and session/account
lifecycle. This tests whether the spec is well-written, NOT whether code works.
**Created**: 2026-06-09
**Feature**: [spec.md](../spec.md)

## Authorization & Privilege Model

- [ ] CHK001 Are the three staff roles and their distinct authorities each fully enumerated (no "etc.")? [Completeness, Spec §FR-002/FR-003]
- [ ] CHK002 Is "everything an admin or reviewer may do" (manager authority) defined by reference to concrete capabilities rather than left open-ended? [Clarity, Spec §FR-003]
- [ ] CHK003 Are the boundaries between admin and reviewer write permissions specified without overlap or gap? [Consistency, Spec §FR-006/FR-007]
- [ ] CHK004 Is the rule "only a manager may create or promote to manager" stated unambiguously for both creation and promotion paths? [Clarity, Spec §FR-004]
- [ ] CHK005 Is "last active manager" defined precisely enough to be testable (what counts as active, how the count is taken)? [Measurability, Spec §FR-005]
- [ ] CHK006 Are the immutability rules for `user_type` and `client_id` specified for every mutation path (create, edit, manager correction)? [Completeness, Spec §FR-009]
- [ ] CHK007 Is it specified that a reviewer's only write capability is the report approve/reject/edit permission, with all other writes excluded? [Clarity, Spec §FR-007]
- [x] CHK008 Are requirements defined for whether a manager may demote/deactivate *themselves* when other managers exist? [Gap, Edge Case] — resolved: allowed only while another active manager remains (Spec §FR-005, §Clarifications)
- [x] CHK009 Are requirements defined for who may list/enumerate the client roster (so staff can pick a target client) versus who may mutate it? [Gap] — resolved: all staff may list/read; only manager mutates (Spec §FR-008, §Clarifications)

## Acting-Client Context & Cross-Client Access

- [ ] CHK010 Is the requirement that every client-scoped staff action must name a target client stated as a universal rule (no implicit "all clients")? [Clarity, Spec §FR-008]
- [ ] CHK011 Are the validation outcomes for a named target client (missing / non-existent / inactive) each specified distinctly? [Completeness, Spec §FR-008/US1]
- [ ] CHK012 Is it specified whether read (browse) actions, not just writes, also require a named acting-client context? [Ambiguity, Spec §FR-008]
- [ ] CHK013 Is the acting-client transport (path param vs header) intentionally deferred to planning and recorded as such, rather than silently missing? [Assumption, Spec §Assumptions]

## Multi-Tenant Isolation (Principle V Reframing)

- [ ] CHK014 Is the reframing of Constitution Principle V (staff cross-client = audited exception; client-users fully isolated) stated explicitly with its rationale? [Completeness, Spec §Assumptions]
- [ ] CHK015 Is "client-users are fully isolated to their own client" stated as an invariant distinct from staff access, with no contradicting clause elsewhere? [Consistency, Spec §FR-022]
- [ ] CHK016 Does the spec flag that the plan's Constitution Check must ratify this reframing (and possibly a governance note), so it is not silently assumed? [Traceability, Spec §Assumptions]
- [ ] CHK017 Are the conditions under which a client-user could be exposed to another client's data explicitly enumerated as impossible (zero cross-client for client-users)? [Coverage, Spec §SC-009]

## Client-Side User Scope (Least-Privilege)

- [ ] CHK018 Is the meaning of an empty/absent client-user scope defined unambiguously as "no visibility" (default-deny)? [Clarity, Spec §FR-014]
- [ ] CHK019 Is the requirement to explicitly choose a scope at creation (full-client vs narrowing) stated as a refusable validation? [Completeness, Spec §FR-014]
- [ ] CHK020 Is the prohibition on a client-user widening their own scope stated for both severity floor and watchlist set? [Consistency, Spec §FR-015]
- [ ] CHK021 Is the cross-client watchlist refusal (a client-A user cannot scope to a client-B watchlist) specified as a hard rule? [Clarity, Spec §FR-014]
- [x] CHK022 Is it specified what happens to a client-user's recorded scope when a scoped watchlist is later deactivated or deleted? [Gap, Edge Case] — resolved: scope persists through soft-deactivation; only hard-delete cascades (Spec §Edge Cases, §Clarifications)
- [ ] CHK023 Is the deferral of client-user login + report-visibility enforcement to the report spec stated, while the stored schema is required to be sufficient now? [Clarity, Spec §FR-016]

## Client Lifecycle (Soft-Delete / Reactivate)

- [ ] CHK024 Are the exact effects of soft-deleting a client enumerated (no new runs, client-user logins blocked, data preserved, reactivatable)? [Completeness, Spec §FR-011]
- [ ] CHK025 Is "all data preserved" defined by listing the data classes retained (documents, watchlists, runs, watermarks, audit)? [Clarity, Spec §FR-011]
- [ ] CHK026 Is the prohibition on hard-deleting a client (and on cascading deletes) stated as an absolute with no exception path? [Consistency, Spec §FR-012]
- [ ] CHK027 Are the effects of reactivating a client specified to be the inverse of soft-delete (runs accepted, client-users may sign in again)? [Coverage, Spec §US2]
- [x] CHK028 Is the in-flight behavior specified when a client is soft-deleted while one of its ingestion runs is already executing? [Gap, Edge Case] — resolved: in-flight run finishes & records; no new run accepted (Spec §Edge Cases, consistent with spec-4 FR-024)

## Report Delivery Configuration

- [ ] CHK029 Are the three per-client delivery fields (regular email, urgent email, urgent threshold) each specified with type, optionality, and default? [Completeness, Spec §FR-017]
- [ ] CHK030 Is email-format validation required with a defined "unchanged on rejection" outcome? [Clarity, Spec §FR-017]
- [ ] CHK031 Is the urgent threshold's default (life-threatening) and its allowed values (the severity ordering) specified? [Measurability, Spec §FR-017]
- [ ] CHK032 Is the "urgent/emergency reports delivered immediately, not batched" requirement recorded as a forward obligation for the notification spec (storage-only here)? [Traceability, Spec §FR-018]
- [x] CHK033 Is it specified whether each delivery field holds a single address or multiple (cardinality)? [Ambiguity, Spec §FR-017] — resolved: single address each; multiple = future improvement (Spec §FR-017, §Future Improvements)

## Migration & Data Integrity

- [ ] CHK034 Is the migration's data-reset scope enumerated exactly (users + dependent referencing rows: ingestion runs/run-sources, user-authored audit)? [Completeness, Spec §FR-023]
- [ ] CHK035 Is the set of preserved data (documents, watchlists, watermarks) stated so no foreign key is left dangling and nothing user-FK-bound is orphaned? [Consistency, Spec §FR-023]
- [ ] CHK036 Is the one-time/idempotent property of the bootstrap-manager seed specified (Alembic-once or "only if no active manager exists")? [Clarity, Spec §FR-024]
- [ ] CHK037 Is the bootstrap manager's credential source (Vault, into memory only) specified with the "never written to disk/migration" constraint? [Completeness, Spec §FR-024]
- [ ] CHK038 Is the apparent tension between "wipe users" and the append-only audit guarantee explicitly reconciled (immutability is a runtime rule, not a migration constraint)? [Conflict, Spec §FR-020/FR-023]
- [ ] CHK039 Is the migration required to be reversible, and is the down-migration behavior for the seeded data specified? [Coverage, Spec §SC-011]
- [ ] CHK040 Is the global-uniqueness rule for login email stated as a constraint spanning both staff and client-users? [Clarity, Spec §FR-025]
- [ ] CHK041 Is the `user_type`/`client_id` integrity rule (staff ⇒ no client; client ⇒ exactly one) stated as an enforceable constraint, not just prose? [Measurability, Spec §FR-001]

## Session, Token & Account Freshness

- [ ] CHK042 Is "authorize from current stored state, not token claims" specified for every authority input (role, type, account-active, client-active)? [Completeness, Spec §FR-019]
- [ ] CHK043 Is the access-token lifetime quantified (~8h) and the expiry behavior (re-login, no refresh token) stated? [Measurability, Spec §FR-019]
- [ ] CHK044 Is the propagation timing of a demotion/deactivation/soft-delete specified as "next request"? [Clarity, Spec §FR-019/SC-007]
- [ ] CHK045 Are refresh tokens explicitly scoped out (future improvement) so their absence is intentional, not an omission? [Assumption, Spec §Future Improvements]

## Auditability

- [ ] CHK046 Is the complete set of audited sensitive writes enumerated (client create/soft-delete/reactivate, staff create/role-change/deactivate, manager creation, client-user create/scope-change, email change)? [Completeness, Spec §FR-021]
- [ ] CHK047 Is "audit log is append-only, even for a manager superuser" stated as an absolute? [Clarity, Spec §FR-020]
- [ ] CHK048 Is the requirement that each cross-client action record the *target client* (not the actor's, since staff have none) stated unambiguously? [Consistency, Spec §FR-021]
- [ ] CHK049 Is the deferral of read/access auditing to the report spec stated, so its absence here is intentional? [Assumption, Spec §FR-021]
- [ ] CHK050 Is the expected audit-entry count per sensitive action specified (exactly one) so it is testable? [Measurability, Spec §SC-008]

## Cross-Cutting Consistency & Traceability

- [ ] CHK051 Does every functional requirement (FR-001..FR-026) have at least one corresponding acceptance scenario or success criterion? [Traceability]
- [ ] CHK052 Are the role/user_type terms used consistently (no synonym drift between "staff admin"/"admin", "client-user"/"client-side user")? [Consistency]
- [ ] CHK053 Are all five user stories' independent-test descriptions phrased so each is demonstrable without the others? [Coverage, Spec §US1–US5]
- [ ] CHK054 Are the deferred-but-designed items (client-user enforcement, report sending, read-audit) each tied to a named later spec rather than vaguely "later"? [Clarity, Spec §Assumptions]
- [ ] CHK055 Is every success criterion (SC-001..SC-011) measurable and technology-agnostic? [Measurability, Spec §Success Criteria]

## Notes

- This is a **requirements-quality** checklist ("unit tests for English"): each item asks whether the
  spec is well-written, not whether the implementation works.
- Mark items `[x]` as you confirm the requirement is complete/clear/consistent/measurable; annotate any
  gaps inline and feed them back into `/speckit-clarify` or the spec before `/speckit-plan`.
- The `[Gap]`/`[Ambiguity]` items surfaced on first pass (CHK008, CHK009, CHK022, CHK028, CHK033) were
  resolved on 2026-06-09 and folded into the spec (§Clarifications + the cited FRs/Edge Cases). No open
  gaps remain; the spec is ready for `/speckit-plan`.
