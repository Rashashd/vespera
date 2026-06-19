# Requirements Readiness Checklist: Report Delivery & Final Wiring Close-Out

**Purpose**: Pre-plan validation that the spec's *requirements* are complete, clear, consistent, and measurable across delivery, security/isolation, the new cross-cutting behaviors, and the frontend/account light-ups — before `/speckit-plan`. Tests the requirements, not the implementation.
**Created**: 2026-06-17
**Feature**: [spec.md](../spec.md)
**Audience / timing**: Author + reviewer, pre-plan readiness gate (standard depth)

## Requirement Completeness

- [x] CHK001 Are the supported delivery channels explicitly enumerated and bounded (email, SFTP), with a clear definition of what makes a channel "configured"? [Completeness, Spec §FR-003]
- [x] CHK002 Is initial-credential / login provisioning for newly-created staff and client-users specified (how a created account first authenticates)? [Gap, Spec §FR-014/FR-015]
- [x] CHK003 Are requirements defined for the case where rendering the delivered document fails (cannot produce the artifact)? [Gap, Spec §FR-002]
- [x] CHK004 Is the per-channel retry policy that precedes declaring a channel "failed" specified? [Gap, Spec §FR-004a]
- [x] CHK005 Are the event types that constitute "client/watchlist-management events" (the admin's audit visibility scope) enumerated? [Completeness, Spec §FR-018]
- [x] CHK006 Is the recipient of the budget-threshold notification specified (which role(s) receive "the agency" alert)? [Gap, Spec §FR-019]
- [x] CHK007 Is the authorization (which roles) for staff-initiated re-send and held-report release defined? [Gap, Spec §FR-006/FR-007a]

## Requirement Clarity & Measurability

- [x] CHK008 Is the no-callback timeout window given a default/bound, or only described as "configurable"? [Clarity, Spec §FR-006a]
- [x] CHK009 Are the SLA Tier-1 / Tier-2 escalation intervals given defaults/bounds rather than only "configured"? [Clarity, Spec §FR-012]
- [x] CHK010 Is the dashboard "delivery success measure" defined (e.g., delivered ÷ dispatched)? [Clarity, Spec §FR-011]
- [x] CHK011 Is the delivered-document content specified precisely enough to validate (required sections/structure), beyond "rendered HTML/structured text"? [Clarity, Spec §FR-002 / Assumptions]
- [x] CHK012 Are the qualitative timing terms ("shortly after approval", "promptly") either quantified or explicitly accepted as non-SLO? [Measurability, Spec §SC-001/SC-003/SC-005]
- [x] CHK013 Is "fresh authorization check" (on reactivation release and re-send) defined in terms of what is re-evaluated? [Ambiguity, Spec §FR-007a/FR-007b]

## Requirement Consistency

- [x] CHK014 Is the definition of `delivered` consistent between the single-channel statement and the all-channels-confirm rule? [Consistency, Spec §FR-004/FR-004a]
- [x] CHK015 Is "staff scoped to the acting client" (report download) consistent with the "staff are not single-client" assumption? [Consistency, Spec §FR-017 / Assumptions]
- [x] CHK016 Is the manager's cross-client audit export reconciled with the absolute client-to-client isolation requirement (the operator exception)? [Consistency, Spec §FR-018/FR-026]
- [x] CHK017 Do US1, US2, the portal, and the metrics requirements all use one canonical delivery-state set (`sent`/`delivered`/`delivery_failed`)? [Consistency, Spec §FR-004/FR-009/FR-010/FR-011]
- [x] CHK018 Is the FR-018 audit-role model free of any lingering contradiction with the spec-10 "manager == admin console rights" it refines? [Consistency, Spec §FR-018 / Assumptions]

## Acceptance Criteria Quality

- [x] CHK019 Does each success criterion (SC-001…SC-011) map to at least one functional requirement and one acceptance scenario? [Traceability, Spec §Success Criteria]
- [x] CHK020 Are the per-story Independent Tests objectively checkable without prescribing implementation? [Measurability, Spec §US1–US8]
- [x] CHK021 Is SC-011 (tracing) verifiable given tracing ships OFF — i.e., are both the on and off outcomes stated? [Acceptance Criteria, Spec §SC-011]

## Scenario & Edge-Case Coverage

- [x] CHK022 Are requirements defined for duplicate / out-of-order / unknown-report callbacks, with the idempotency basis stated? [Coverage, Spec §FR-005 / Edge Cases]
- [x] CHK023 Are recovery requirements defined for both held paths — no-channel and suspended — including how and when each releases? [Coverage, Spec §FR-007/FR-007a]
- [x] CHK024 Are mixed multi-channel-outcome requirements (one confirms, one fails) complete, including targeted re-send of only the failed channel? [Coverage, Spec §FR-004a / Edge Cases]
- [x] CHK025 Is it explicit that a delivered batch report contains only its included findings (dropped/discarded excluded)? [Coverage, Spec §Edge Cases]
- [x] CHK026 Are SLA boundary conditions (approve-just-before-deadline, clock skew, repeated ticks) addressed in requirements? [Edge Case, Spec §FR-013 / Edge Cases]
- [x] CHK027 Is the suspend→reactivate restore scenario specified well enough to distinguish suspension-paused watchlists from manually-deactivated ones? [Coverage, Spec §FR-007b / Assumptions]

## Non-Functional (Security / Privacy / Observability)

- [x] CHK028 Are the PII-free guarantees for delivery/notification logs and for worker traces stated as verifiable requirements? [Coverage, Spec §FR-024/FR-029/SC-009/SC-011]
- [x] CHK029 Is the callback-authentication requirement stated as a testable property (only the routing layer can call it)? [Clarity, Spec §FR-005]
- [x] CHK030 Is secret handling for routing-layer and per-client SFTP credentials stated as a requirement (no plaintext), even with the storage location deferred to planning? [Completeness, Spec §FR-025]
- [x] CHK031 Is the "tracing OFF by default" invariant stated unambiguously and consistently across the requirement and its acceptance criteria? [Consistency, Spec §FR-027/FR-028/SC-011]

## Ambiguities, Dependencies & Assumptions

- [x] CHK032 Is "assigned reviewer" (SLA Tier-1 target) a defined concept, given reports may sit in a shared reviewer queue with no assignee? [Ambiguity, Spec §FR-012]
- [x] CHK033 Is the assumption that staff and client-user account-CRUD endpoints already exist recorded and validated (so US4 is wiring only)? [Assumption, Spec §Assumptions/US4]
- [x] CHK034 Is the assumption that budget warning/exceeded domain events already exist validated for US6? [Assumption, Spec §FR-019/Assumptions]
- [x] CHK035 Are the cross-spec dependencies (9 / 10 / 11 / 12 / 3 / 4b) each tied to a concrete artifact this spec relies on, and is the n8n-mocked-in-CI assumption stated so acceptance scenarios don't require a live routing layer? [Traceability/Assumption, Spec §Dependencies/Assumptions]

## Notes

- ✅ **All 35 items closed 2026-06-17** via spec edits (FR-002/003/004/004a/005/006/006a/007/011/012/016a/018/019/026 + Assumptions + a readiness-gate Clarifications sub-session). See spec §Clarifications → "Session 2026-06-17 — readiness-gate closures".
- Check items off as resolved: `[x]`. An unresolved item means the **spec** needs a tweak before `/speckit-plan`, not that code is wrong.
- High-signal gaps to weigh first: CHK002 (account credential provisioning), CHK005 (admin audit event-category enumeration), CHK006/CHK007 (notification recipient + re-send authorization), CHK008/CHK009 (timeout & escalation interval defaults), CHK032 ("assigned reviewer" may not exist as a concept).
- Items reference `[Spec §X]` or carry `[Gap]`/`[Ambiguity]`/`[Conflict]`/`[Assumption]` markers; ~100% are traceable.
