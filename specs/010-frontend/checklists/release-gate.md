# Requirements Quality Gate Checklist: Frontend SPA (Spec 010)

**Purpose**: Release-gate validation of requirement quality (completeness, clarity, consistency, measurability, coverage) BEFORE planning/implementation. These are "unit tests for the spec's English" — they test whether the requirements are written well enough for a cold, less-capable implementer to build without guessing, NOT whether any code works.

**Created**: 2026-06-14
**Feature**: [spec.md](../spec.md)
**Depth**: Release gate (thorough) · **Scope**: All domains (HITL, isolation/auth, client portal, admin console, observability/cost, supporting endpoints)
**Worked through**: 2026-06-14 — all 53 items evaluated against spec.md; gaps patched back into the spec (see Notes).

## Requirement Completeness

- [x] CHK001 - Are read AND write permissions specified for every surface for all four user types (manager/admin/reviewer/client-user)? [Completeness, Spec §FR-002/004]
- [x] CHK002 - Is the acting-client switcher fully specified for first login with no prior selection, and for a previously-selected client the staff user can no longer access? [Completeness, Spec §FR-004a]
- [x] CHK003 - Are pagination requirements for the reviewer queue (page size, loading beyond page 1, ordering stability) defined? [Spec §FR-007]
- [x] CHK004 - Is the structured-claim shape (text, provenance, optional source_ref) and corroboration-source shape specified completely enough to render without inferring keys? [Completeness, Spec §FR-008/009]
- [x] CHK005 - Is the passage-unavailable fallback fully specified (what is shown, whether the reviewer may still act)? [Completeness, Spec §FR-010]
- [x] CHK006 - Are requirements defined for displaying the reject/redraft comment history the reviewer sees across rounds? [Spec §FR-008/013]
- [x] CHK007 - Are zero-state requirements defined for the client portal (client with no watchlists; watchlist with no sent reports)? [Completeness, Spec §FR-023]
- [x] CHK008 - Are the cost dashboard's fields and aggregation granularity (totals vs per-call-site, currency, time window) specified? [Completeness, Spec §FR-021/033]
- [x] CHK009 - Is it specified whether manager and admin have identical admin-console rights, or which actions differ? [Spec §FR-022]
- [x] CHK010 - Are requirements defined for what a usage record must contain so per-client cost can be reconstructed (all fields enumerated)? [Completeness, Spec §FR-033]

## Requirement Clarity & Ambiguity

- [x] CHK011 - Is "sent/delivered" defined as the exact set of report statuses that make a report visible to a client-user? [Clarity, Spec §FR-023/030 + Assumptions]
- [x] CHK012 - Is "expedited-first" ordering disambiguated with a tie-break rule among multiple expedited reports? [Spec §FR-007]
- [x] CHK013 - Does the redraft requirement state unambiguously whether the cap of 3 counts rejections, and what the 4th rejection produces? [Clarity, Spec §FR-013]
- [x] CHK014 - Are the allowed `provenance` values enumerated, with a clear rule for which require a resolvable `source_ref`? [Clarity, Spec §FR-008 + Key Entities]
- [x] CHK015 - Is the per-model pricing source and unit (per-token vs per-1K, currency) stated unambiguously? [Clarity, Spec §FR-033/035]
- [x] CHK016 - Is watchlist attribution for expedited reports lacking a direct watchlist link defined precisely (tie-break when a document maps to multiple watchlists)? [Spec §FR-023/030]
- [x] CHK017 - Is the acting-client selection's persistence scope clear (per device/browser)? [Clarity, Spec §FR-004a]
- [x] CHK018 - Are vague qualifiers ("clear message", "explicit empty state") tied to verifiable conditions? [Spec §FR-005/026]

## Requirement Consistency

- [x] CHK019 - Are UI role-gating requirements (FR-004/016/022/025) consistent with the rule that the API is the authoritative boundary (FR-027)? [Consistency]
- [x] CHK020 - Do client-portal visibility (FR-023) and the client-read endpoint (FR-030) describe the identical status filter and watchlist grouping? [Consistency]
- [x] CHK021 - Do the reviewer-action FRs (FR-011..015) match the acceptance scenarios in User Stories 1 and 2? [Consistency]
- [x] CHK022 - Is "show all N corroborating sources" consistent with the constitution's Grounding principle? [Consistency, Spec §FR-009]
- [x] CHK023 - Has all residual "approved/delivered" phrasing been reconciled to "sent/delivered"? [Consistency]
- [x] CHK024 - Is older "graceful unavailable / may-not-exist" language for cost/manual-trigger reconciled with the now-built requirements? [Conflict resolved, Spec §FR-020/021/032-035]
- [x] CHK025 - Are entity terms used consistently (claim vs structured field; finding vs report-finding; watchlist page)? [Consistency, Spec Key Entities]

## Acceptance Criteria Quality & Measurability

- [x] CHK026 - Can SC-002 be objectively verified (displayed source count equals corroboration_count)? [Measurability, Spec §SC-002]
- [x] CHK027 - Is SC-001's "typical report" defined so the under-3-minutes target is testable? [Measurability, Spec §SC-001]
- [x] CHK028 - Can SC-011 be measured without ambiguity about rounding/currency? [Measurability, Spec §SC-011/FR-033]
- [x] CHK029 - Does SC-010 define which surfaces count as "primary" so test coverage is verifiable? [Measurability, Spec §SC-010]
- [x] CHK030 - Is SC-004's "0 forbidden surfaces reachable" stated as a checkable condition across navigation and direct URL? [Measurability, Spec §SC-004]

## Scenario & Edge-Case Coverage

- [x] CHK031 - Are alternate-flow requirements defined for edit-then-approve when only some claims are edited? [Coverage, Spec §FR-012]
- [x] CHK032 - Are exception-flow requirements defined per reviewer action for server failure (409/422/network), including not optimistically showing success? [Coverage, Spec §FR-017/026]
- [x] CHK033 - Are recovery requirements defined for a report opened while mid-redraft? [Coverage, Spec Edge Cases]
- [x] CHK034 - Is behavior defined when a staff user's selected acting-client becomes suspended/inaccessible mid-session? [Coverage, Spec §FR-004a]
- [x] CHK035 - Is the UI consequence of the empties-batch → auto-discard rule specified? [Coverage, Spec §FR-015 / US2]
- [x] CHK036 - Are large-data requirements defined (finding with many sources; batch with many findings) without truncating the corroboration count? [Edge Case, Spec Edge Cases]
- [x] CHK037 - Is session expiry mid-edit/mid-comment covered, including no misleading success? [Edge Case, Spec Edge Cases]
- [x] CHK038 - Is behavior defined when a usage/cost record write fails but the LLM call succeeded? [Edge Case, Spec §FR-033]

## Non-Functional Requirements

- [x] CHK039 - Are accessibility requirements for reviewer surfaces defined or explicitly scoped out? [NFR, Spec §FR-028]
- [x] CHK040 - Is client-side token storage stated with its mitigations (CSP, token lifetime) as a testable expectation? [NFR, Spec Assumptions]
- [x] CHK041 - Are PII/secret-redaction requirements for traces and usage records stated as verifiable constraints? [NFR, Spec §FR-035]
- [x] CHK042 - Is the observability scope bounded so locally-run ONNX models are excluded from tracing/cost? [NFR, Spec §FR-032]
- [x] CHK043 - Are loading/latency expectations specified or intentionally omitted with rationale? [NFR, Spec Assumptions]

## Dependencies & Assumptions

- [x] CHK044 - Is the dependency on spec 9's live `ReportResponse`/reviewer routes documented with contract-drift risk? [Assumption, Spec Assumptions]
- [x] CHK045 - Is the dependency on spec 13 for "sent" status documented as intended (portal empty until then)? [Assumption, Spec Assumptions]
- [x] CHK046 - Is the assumption that `ReportStatus` includes a "sent" value validated? [VALIDATED: it does NOT — documented + forward dependency recorded for spec 13. Spec Assumptions]
- [x] CHK047 - Are the three new backend read endpoints' authorization rules documented as reusing existing per-client/role guards? [Dependency, Spec §FR-029..031]
- [x] CHK048 - Is the new usage/cost persistence store (new migration) explicitly acknowledged? [Dependency, Spec §FR-033]
- [x] CHK049 - Is the triage LLM call's bypass of LangChain documented as requiring explicit instrumentation? [Assumption, Spec §FR-032]

## Anti-Hallucination & Traceability (cold-implementer readiness)

- [x] CHK050 - Does the spec clearly separate frontend vs backend requirements so a cold implementer builds both halves? [Clarity, Spec §FR-029..035]
- [x] CHK051 - Is each functional requirement traceable to at least one acceptance scenario or success criterion? [Traceability]
- [x] CHK052 - Is the FR/SC ID scheme complete and consistent (no duplicate or skipped IDs)? [VERIFIED: FR-001..035 + FR-004a contiguous; SC-001..011 present and reordered. Traceability]
- [x] CHK053 - Are named external/internal contracts stated as they exist in live code, with not-yet-existing items explicitly marked as to-be-built? [Clarity, Spec Assumptions]

## Notes

- **Result**: 53/53 items now satisfied after patching the spec on 2026-06-14. "Checked" means the *requirement is written well enough*, not that any implementation works.
- **Gaps the gate caught and that were patched into the spec**: acting-client switcher edge cases (FR-004a); expedited tie-break ordering + queue pagination (FR-007); manager/admin console parity (FR-022); accessibility scope declared (FR-028); read-latency stance (Assumptions); claim-provenance values enumerated (FR-008 + Key Entities); pricing unit/currency (FR-033); expedited→single owning watchlist (FR-023); "typical report" defined (SC-001); usage-store migration acknowledged (FR-033); SC ordering fixed.
- **Biggest finding (CHK046)**: the live `ReportStatus` enum has **no `sent` value** (`approved` is terminal). **Visibility model revised 2026-06-14** (supersedes "sent-only"): client-user sees **approved + sent** (portal populated in v1 by approved); reviewer sees **all reports** (FR-006a); each report shows a **delivery status** (FR-006b) — "Approved (pending delivery)" now, Sent/Delivered/Delivery-failed once spec 13 sets them. The `sent`/`delivery_failed` statuses + lighting up the spec-10 delivery display remain a **forward dependency on spec 13**, recorded in spec.md Assumptions + the build-plan + forward-dependency ledger.
- Items remaining spec-level ambiguous (none currently) would be resolved in `implementation-notes.md` at plan time per the project's anti-hallucination rule.

## Revised-Model Gate (added 2026-06-14 with the approved+sent / all-reports / delivery-status revision)

- [x] CHK054 - Is client visibility precisely defined as the status set {approved, sent, delivered}, excluding in-workflow states, consistently across FR-023/FR-030/SC-008/US5? [Consistency/Clarity]
- [x] CHK055 - Is the reviewer all-reports view specified as distinct from the drafts action queue, with all-status listing and read-only detail reuse? [Completeness, Spec §FR-006a]
- [x] CHK056 - Is the per-report delivery-status display specified with its v1 fallback ("Approved (pending delivery)") and the spec-13-set Sent/Delivered/Delivery-failed + `delivered_at` values? [Clarity, Spec §FR-006b]

## Design-Expansion Gate (added 2026-06-14 — FR-021a/036/037/038/039/040/041 + SC-012)

- [x] CHK057 - Is the operations dashboard (FR-021a) specified with its buildable-now metrics AND its delivery metrics marked as a spec-13 forward dependency (null/"pending"), with a documented `/clients/{id}/metrics` contract? [Completeness/Consistency, Spec §FR-021a + contracts/backend-endpoints.md]
- [x] CHK058 - Are the report-download (FR-036) and audit-export (FR-037) controls specified as forward-dependency buttons that render disabled ("export not yet available") with a reason, never erroring, and light up with no UI restructuring? [Clarity, Spec §FR-036/037]
- [x] CHK059 - Is the theme toggle (FR-038) specified (persisted, default light, both-mode contrast) consistent with FR-028's a11y stance? [Consistency, Spec §FR-038]
- [x] CHK060 - Is the shell (FR-039) specified — collapsible sidebar (auto-collapse on detail to avoid the layout-C rail collision) + top bar, no dead ends, role-gated nav? [Completeness, Spec §FR-039 + design-system §6]
- [x] CHK061 - Is the citation-review + soft approve gate (FR-040) specified as a NON-blocking aid that preserves the reviewer's final authority (Principle I) while making grounding verification explicit (Principle II), with SC-012 measuring it? [Constitution/Measurability, Spec §FR-040/SC-012]
- [x] CHK062 - Is the command palette (FR-041) specified as an accelerator layered over (never replacing) normal navigation, with a test? [Clarity, Spec §FR-041 + tasks T056a]
- [x] CHK063 - Are the new backend additions (`metrics_routes.py`, FR-021a) reflected in the READ-FIRST implementation-notes file list + router wiring so a cold implementer creates them? [Cold-implementer, contracts/implementation-notes.md §3/§8]
