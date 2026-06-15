# Feature Specification: Durable ARQ Job Orchestration & Cron Scheduling

**Feature Branch**: `011-arq-scheduling`

**Created**: 2026-06-15

**Status**: Draft

**Input**: User description: "011-arq-scheduling — Durable ARQ job orchestration + cron scheduling for the Pantera pipeline. Replace in-process BackgroundTasks with a reliable, durable queue so the multi-stage pipeline survives restarts, retries transient failures, never double-processes, dead-letters poison jobs, and shuts down gracefully; add cron-driven automation so each watchlist's cadence drives an end-to-end cycle without a human pressing a button."

## Overview

Today every stage of Pantera's monitoring pipeline (ingestion → index build → triage → expedited
drafting → reviewer redraft → batch consolidation) runs as in-process background work attached to the
web request that triggered it. If the web process restarts, is redeployed, or crashes mid-job, that
work is lost silently with no retry, no record, and no operator visibility. Separately, each watchlist
carries a monitoring **cadence** (daily / weekly / biweekly / monthly) that today drives *nothing*
automatically — an operator must manually trigger ingestion, then index build, then consolidation for
every watchlist, every cycle.

This feature makes pipeline work **durable** (survives restarts, retries transient failures, never
double-processes, records poison jobs, drains cleanly on shutdown) and makes the monitoring cadence
**automatic** (a scheduler runs each due watchlist's full cycle end-to-end without human intervention).
It changes *how* and *when* existing pipeline work runs; it does not change what each stage produces,
and it does **not** weaken the human-in-the-loop gate — drafting still stops at the reviewer, and
nothing is ever sent (delivery is a later feature).

## Clarifications

### Session 2026-06-15

- Q: What should the committed golden-set / eval gate assert for this infra spec? → A: A **due-selection golden set** (labeled fixtures → expected due watchlists) scored `precision = 1.0` and `recall = 1.0`, **plus** reliability invariants `duplicate_rate = 0`, `loss_rate = 0`, `transient_retry_recovery = 1.0`, and `inline_vs_durable_parity = 1.0`, all committed to `eval_thresholds.yaml` and gated in the CI `eval` job.
- Q: How often should the scheduler scan for due watchlists? → A: An **hourly** tick (the scheduler runs every hour, scans for due watchlists, and enqueues a cycle for any whose cadence interval has elapsed); due-ness computed in UTC, accurate to ~1 hour.
- Q: How is per-watchlist cycle state stored? → A: A dedicated **`watchlist_cycles` table** (migration 0010), one row per cycle (watchlist_id, client_id, status in_progress/completed/failed, current_stage, started_at, completed_at, links to the ingestion/index runs). Due-ness = latest completed row; the in-progress guard = any open row; keeps full cycle history.
- Q: What is the job-level retry budget on top of in-call tenacity? → A: **3 job-level tries** with exponential backoff before dead-lettering. Transient (retryable) = infra/timeout/5xx/process-death; permanent (no retry) = 4xx-class / validation / business-rule rejections. The existing in-call `tenacity` (`stop_after_attempt(3)`, no-retry-on-4xx) stays underneath each external call.
- Q: When a stage dead-letters mid-cycle, what does the next scheduler tick do? → A: **Manual recovery, no auto-retry of the cycle.** A `failed` cycle is excluded from auto-scheduling (it does not silently re-run; due-ness advances only on `completed`). The operator recovers via the existing idempotent manual stage triggers (FR-019): **resume** the failed stage, **restart** a fresh cycle, or **abandon** (close the failed cycle so the watchlist returns to normal cadence at its next due time). The per-stage 3-try job retry (already exhausted at dead-letter time) is the only automatic retry.

### Session 2026-06-15 (second pass)

- Q: How does a per-watchlist cadence cycle map onto the index step, which is per-client today? → A: **The cycle's index step is watchlist-scoped (Option B).** Each cycle indexes only the triggering watchlist's documents and records the index run against that watchlist, giving clean, auditable per-cycle provenance. This requires extending the existing index-build machinery: add `watchlist_id` to the index-build run, change the single-running guard from per-client to **per-(client, watchlist)**, and filter document selection to the watchlist. The existing client-wide manual rebuild capability is preserved. Implication: this touches the prior index-build schema, so `implementation-notes.md` MUST pin the exact constraint migration and the full caller list to de-risk the cold implementation.
- Q: Does end-of-cycle consolidation wait for per-finding expedited draft jobs? → A: **No — independent, no join (Option A).** Triage fans out per-finding expedited draft jobs (each durable, idempotent, independently retried/dead-lettered). End-of-cycle batch consolidation runs over the cycle's routine findings and does **not** wait for expedited drafts. The cycle is marked `completed` when consolidation finishes; a still-running or failed expedited draft is tracked and surfaced independently (its own dead-letter record), not as part of cycle completion.
- Q: Do automated cycles run for watchlists of a suspended client? → A: **No — exclude suspended clients (Option A).** Due-selection requires the **client** to be `active` in addition to an active, non-empty watchlist; a suspended client gets no automated cycles and no spend. On reactivation the watchlist becomes due again at its next interval. Manual triggers remain governed by the existing `CLIENT_SUSPENDED` guard.
- Q: After extended downtime, how many cycles does an overdue watchlist run on recovery? → A: **Coalesce — one catch-up cycle (Option A).** A watchlist overdue by any number of intervals runs exactly **one** cycle on recovery (ingestion uses the existing per-source watermarks to pick up everything since the last run); the next due time is computed forward from that cycle's completion. Missed intervals are not replayed one-per-period.

- Q: Should automated cycles respect the per-watchlist budget (which is advisory/soft today and unenforced)? → A: **No auto-stop by default; agency-chosen per-watchlist policy + near-cap notification.** Add a configurable `budget_exceeded_policy` per watchlist: **`continue`** (default — budget stays advisory, full automated cycles proceed, matching today's behavior), **`critical_only`** (over cap: automated cycle still drafts expedited reports for urgent/emergency findings but skips the routine end-of-cycle batch consolidation), and **`pause`** (over cap: automated cycle skips all LLM drafting, but serious-finding detection/escalation/operator-alerting still occur per Constitution III, and manual/reviewer triggers always override). The agency is **notified** as a watchlist nears (existing 80% warning threshold) and reaches its cap; spec 11 records budget-state transitions as domain events surfaced on the cost dashboard + audit log, while the **active notification send is deferred to spec 13 (n8n)**. Making the warning threshold configurable (e.g., 90%) remains the existing spec-3 backlog item.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Pipeline work survives restarts and transient failures (Priority: P1)

As the platform operator team, when a monitoring job is running and the web or worker process is
restarted, redeployed, or crashes — or when an upstream source / model service has a transient blip —
the job must not be silently lost. It is picked up and completed by a durable worker, retried on
transient failure with backoff, and never processed twice even if it is enqueued or retried more than
once.

**Why this priority**: This is the core reliability guarantee and the reason the feature exists. In a
regulated pharmacovigilance context, a silently dropped ingestion or triage run can mean a missed
serious adverse event. Durable, idempotent execution is the minimum viable outcome — every other story
builds on it.

**Independent Test**: Trigger each pipeline stage; kill/restart the worker mid-job and confirm the job
completes exactly once; inject a transient failure and confirm retry-then-success; enqueue the same job
twice and confirm the underlying work runs only once. Fully testable without cron or any UI.

**Acceptance Scenarios**:

1. **Given** an ingestion run has been triggered and the worker is restarted before it finishes,
   **When** the worker comes back up, **Then** the run completes and its results are persisted exactly
   once (no duplicate documents, no duplicate findings).
2. **Given** a job calls an external source/model that returns a transient error, **When** the job
   runs, **Then** it retries with bounded attempts and backoff and ultimately succeeds without operator
   action.
3. **Given** a job calls an external dependency that returns a permanent (client-error) response,
   **When** the job runs, **Then** it does **not** retry and is recorded as failed.
4. **Given** the same logical job (same run / finding / report / watchlist-cycle) is enqueued twice,
   **When** both attempts are processed, **Then** the work is performed only once and no duplicate
   state is written.
5. **Given** in-flight jobs and a graceful shutdown signal, **When** the worker is asked to stop,
   **Then** it stops accepting new jobs and finishes (or safely releases) in-flight work within a
   bounded grace period before exiting.

---

### User Story 2 - Watchlists run their full cycle automatically on cadence (Priority: P2)

As a manager/admin, I configure a watchlist's cadence (daily / weekly / biweekly / monthly) and the
platform automatically runs that watchlist's **entire** monitoring cycle on schedule — ingestion, then
index build, then triage, then expedited drafting for any urgent/emergency findings, then a
consolidated batch report at the end of the cycle — without anyone pressing a button. Manual triggering
remains available for on-demand runs.

**Why this priority**: This is the headline operator value — it turns a per-stage manual chore into a
hands-off monitoring service and is what "scheduling" means to the business. It depends on durable
execution (P1) being in place first.

**Independent Test**: Set watchlists to different cadences and last-cycle timestamps; advance the clock
/ run the scheduler tick; confirm exactly the **due** watchlists start a cycle, that each cycle advances
through all stages to completion, and that not-yet-due, inactive, or empty watchlists are skipped.

**Acceptance Scenarios**:

1. **Given** an active, non-empty watchlist whose cadence interval has elapsed since its last completed
   cycle, **When** the scheduler tick runs, **Then** a new end-to-end cycle is started for that
   watchlist.
2. **Given** a watchlist whose interval has **not** elapsed, or which is inactive or has no items,
   **When** the scheduler tick runs, **Then** no cycle is started for it.
3. **Given** a cycle has been started for a watchlist, **When** each stage completes, **Then** the next
   stage is automatically started, ending with a consolidated batch report for that cycle.
4. **Given** a watchlist already has a cycle in progress, **When** the scheduler tick runs again before
   it finishes, **Then** a duplicate concurrent cycle is **not** started.
5. **Given** a cycle completes, **When** the next scheduler tick runs after the cadence interval again
   elapses, **Then** the next cycle starts; the cadence interval is measured from cycle completion.
6. **Given** automated cycles are running, **When** an operator manually triggers a stage on demand,
   **Then** the manual trigger still works and is subject to the same single-in-flight protection.

---

### User Story 3 - Operators can see and act on failed / dead-lettered jobs (Priority: P3)

As a manager/admin, when a job ultimately fails (exhausts its retries), I can see that it failed —
which job, for which client, when, how many attempts, and why — on the admin dashboard and in the
immutable audit trail, so I can investigate and re-trigger the work rather than discovering a silent
gap days later.

**Why this priority**: Visibility closes the reliability loop — durable retry is only trustworthy if a
human is told when it finally gives up. It is P3 because the safety-critical guarantees (don't lose,
don't duplicate) are delivered by P1; this story is about operator awareness and follow-up.

**Independent Test**: Force a job to exhaust its retries; confirm a dead-letter record is created with
the expected attributes, a system-attributed audit event is written to the append-only audit log, and
the admin dashboard surfaces the failure on a failed-jobs card.

**Acceptance Scenarios**:

1. **Given** a job that exhausts its retry budget, **When** the final attempt fails, **Then** a
   dead-letter record is persisted capturing the job type, the target client, the failure reason, the
   attempt count, and timestamps.
2. **Given** a job is dead-lettered, **When** the failure is recorded, **Then** a system-attributed
   event is written to the append-only audit log (no human actor, immutable).
3. **Given** dead-lettered jobs exist, **When** a manager/admin opens the admin dashboard, **Then** a
   failed-jobs / dead-letter surface shows the current failures with enough context to investigate.
4. **Given** PII or secrets could appear in a job's inputs, **When** any failure detail is logged or
   stored, **Then** it contains no patient identifiers or secrets.

---

### Edge Cases

- **Worker absent in production**: if no worker is running, triggered work is enqueued and waits
  durably; it is not lost and not silently executed in the web process. (In-process execution is a
  dev/test-only mode and is never used in production.)
- **Redis/broker unavailable**: the system refuses to start (or surfaces a clear failure) rather than
  pretending work was queued; consistent with the platform's "refuse to boot if dependencies
  unreachable" rule.
- **Duplicate scheduler ticks / overlapping ticks**: a watchlist that is already mid-cycle is not
  started again; deterministic per-cycle identity prevents stampedes.
- **Stage failure mid-cycle**: if a stage in an automated cycle dead-letters, the cycle does not silently
  advance as if it succeeded; it is marked `failed` (recording the stage), the failure is recorded and
  surfaced, and the cycle is excluded from auto-scheduling until an operator resumes, restarts, or abandons
  it (the cycle never falsely marks itself complete and never silently auto-re-runs).
- **Cadence changed mid-cycle**: changing a watchlist's cadence affects when the *next* cycle is due; it
  does not abort an in-flight cycle.
- **Clock / timezone**: due-ness is evaluated consistently in UTC so cadence intervals are unambiguous.
- **Empty cycle**: a due watchlist that yields no new documents still completes its cycle cleanly
  (consolidation may produce an empty/"nothing this cycle" outcome) and records completion so the next
  due time advances.
- **Long-running job exceeding grace period on shutdown**: work that cannot finish within the shutdown
  grace window is left in a re-runnable state (not marked complete) so it is safely retried, not lost.
- **Extended downtime / overdue by many intervals**: the watchlist runs a single coalesced catch-up cycle
  on recovery (not one per missed interval); the next due time advances from that cycle's completion.
- **Client suspended while a cycle is in progress / between cycles**: a suspended client's watchlists are
  excluded from future auto-scheduling; manual triggers remain blocked by the existing `CLIENT_SUSPENDED`
  guard. On reactivation, normal cadence scheduling resumes from the next interval.

## Requirements *(mandatory)*

### Functional Requirements

**Durable execution (replaces in-process background work)**

- **FR-001**: The system MUST execute all pipeline stages — ingestion, index build, triage, expedited
  drafting, reviewer-rejection redraft, and batch consolidation — as durable queued jobs processed by a
  dedicated worker, rather than as in-process background tasks attached to a web request. This includes the
  **manual `consolidate-batch` endpoint**, which today runs the consolidation **inline in the request**
  (blocking on the drafting agent); it MUST be converted to enqueue the consolidation job and return `202`
  like the other manual triggers. (Changing it from a synchronous report response to `202` is a
  cross-spec UI concern — see the frontend forward-dependency ledger.)
- **FR-002**: Each durable job MUST survive a restart of the web and/or worker process: a job that was
  queued or in progress before a restart MUST be picked up and run to completion afterward.
- **FR-002a**: If the broker is unreachable **at enqueue time**, the enqueue MUST fail visibly — a
  human-triggered request returns an error rather than appearing to succeed, and a scheduler-tick enqueue
  logs the failure and is retried on the next tick. Work MUST NOT be silently dropped, and MUST NOT
  silently fall back to inline execution in production.
- **FR-003**: The system MUST provide a configuration-gated **inline execution mode** for development
  and testing that runs jobs in the calling process without a worker or broker. This mode MUST default
  to OFF and MUST never be enabled in production; production execution is always durable/queued.
- **FR-004**: Switching between durable mode and inline mode MUST NOT change the *outcome* of a job —
  the same inputs produce the same persisted results in both modes (behavioral parity).

**Idempotency**

- **FR-005**: Each job MUST be idempotent with respect to its logical work key (ingestion run, index
  build run, finding+revision, report, or watchlist cycle): enqueuing or retrying the same logical job
  more than once MUST NOT produce duplicate persisted state or perform the work twice.
- **FR-006**: The system MUST preserve single-in-flight protection against concurrent duplicate work. For
  the cycle's index step this guard becomes **per-(client, watchlist)** (see FR-014a); other single-in-
  flight protections are preserved.

**Retry & failure handling**

- **FR-007**: Transient failures (timeouts, transient network/5xx, dependency temporarily unavailable,
  process death) MUST be retried at the job level with a bounded budget of **3 tries** and exponential
  backoff between attempts. This job-level retry sits on top of the existing in-call `tenacity`
  (`stop_after_attempt(3)`) on individual external calls.
- **FR-008**: Permanent failures (client-side / 4xx-class errors, invalid input) MUST NOT be retried.
- **FR-009**: A job that exhausts its retry budget MUST be recorded as **dead-lettered** in a durable
  store capturing at minimum: job type, target client, a digest of its inputs, the failure reason, the
  attempt count, and timestamps.
- **FR-009a**: Dead-letter records MUST be retained for at least a **configurable retention window
  (default 90 days)** for operator investigation, after which they MAY be purged; purging dead-letter
  records MUST NOT remove the corresponding append-only audit entries (FR-010).
- **FR-010**: When a job is dead-lettered, the system MUST write a system-attributed (no human actor)
  event to the append-only audit log.
- **FR-011**: Dead-letter records and audit entries MUST contain no patient identifiers and no secrets.

**Graceful shutdown**

- **FR-012**: On a shutdown signal, the worker MUST stop accepting new jobs and allow in-flight jobs to
  finish (or be safely released for re-run) within a **bounded, configurable grace period (default: the
  worker's maximum per-job timeout)** before exiting; work that cannot finish in time MUST be left in a
  re-runnable state, never marked complete.

**Cron scheduling — full cadence loop**

- **FR-013**: The system MUST run a recurring scheduler on an **hourly** tick that scans watchlists and
  selects those that are **due** — belonging to an **active (non-suspended) client**, active, non-empty,
  and whose cadence interval has elapsed (evaluated in UTC) since their last completed cycle. Watchlists of
  a suspended client MUST NOT be auto-scheduled; on client reactivation they become due again at their next
  interval.
- **FR-014**: For each due watchlist, the system MUST start a durable end-to-end cycle that runs, in
  order: ingestion → index build → triage → expedited drafting (for each urgent/emergency finding) →
  and, at the end of the cycle, a batch report consolidation for that watchlist.
- **FR-014a**: The cycle's index-build step MUST be **scoped to the triggering watchlist's documents**
  (not the whole client). The index-build run MUST record which watchlist it served, and the single-
  running guard MUST be **per-(client, watchlist)** rather than per-client, so cycles for different
  watchlists of the same client can proceed independently and each cycle has clean, auditable provenance
  over exactly the documents it processed. The existing client-wide manual rebuild capability MUST be
  preserved alongside the watchlist-scoped path.
- **FR-015**: The cycle MUST advance stage-to-stage by job completion (each stage starts the next on
  success) rather than by inline calls inside a single long-running task.
- **FR-015a**: Per-finding expedited draft jobs fanned out by triage MUST be independent durable jobs
  (each idempotent, retried, and dead-lettered on its own). End-of-cycle batch consolidation MUST NOT wait
  for expedited drafts to finish; the cycle is marked `completed` when consolidation completes. A
  still-running or failed expedited draft is tracked and surfaced independently of cycle completion.
- **FR-015c**: Expedited-draft fan-out MUST be bounded — it is subject to the worker's global concurrency
  limit and MUST NOT spawn unbounded simultaneous drafts; excess drafts are queued durably and processed
  as capacity frees, so one cycle's fan-out cannot starve the queue.
- **FR-015b**: A watchlist that is overdue by more than one cadence interval (e.g., after extended worker
  downtime) MUST run exactly **one** coalesced catch-up cycle on recovery, not one cycle per missed
  interval. Ingestion relies on the existing per-source watermarks to cover everything accumulated since
  the last run; the next due time is computed forward from the catch-up cycle's completion.
- **FR-016**: The system MUST track each watchlist's cycle state in a dedicated cycle-history store (one
  record per cycle: watchlist, client, status of in-progress/completed/failed, current stage, start and
  completion timestamps, and links to that cycle's ingestion/index runs) so due-ness can be computed from
  the latest completed cycle (next due time measured from completion) and an in-progress cycle can be
  detected as an open record.
- **FR-017**: The scheduler MUST NOT start a new cycle for a watchlist that already has a cycle in
  progress.
- **FR-018**: A stage failure within an automated cycle MUST NOT cause the cycle to be marked complete;
  the failure MUST be recorded (per FR-009/FR-010) and the cycle marked `failed` (recording the stage at
  which it failed) in an operator-visible state.
- **FR-018a**: A watchlist whose **latest cycle is `failed` and not yet resolved** MUST be **excluded from
  auto-scheduling**: the due-selection MUST treat such a watchlist as NOT due and the scheduler MUST NOT
  start, re-run, or advance a cycle for it on any later tick (the per-stage job retry budget of FR-007 is
  the only automatic retry). This exclusion is in addition to the in-progress guard (FR-017): a watchlist
  is due only when its latest cycle is `completed` (or none exists) **and** there is no open `in_progress`
  **and** no unresolved `failed` cycle. (Note: keying due-ness on the last `completed` cycle alone is
  insufficient — a `failed` cycle is not `completed`, so without this explicit exclusion the watchlist
  would wrongly appear due and auto-restart.)
- **FR-018b**: An operator MUST be able to recover a `failed` cycle: **resume** the failed stage via the
  existing idempotent manual trigger (re-run that continues the chain without duplicating prior stages),
  **restart** a fresh cycle via the manual trigger, or **abandon** it — an explicit action that marks the
  failed cycle **resolved** so the watchlist is no longer excluded and returns to normal cadence scheduling
  at its next interval. Resume and restart, by creating a new in_progress/completed cycle, also clear the
  exclusion. A one-click in-UI cycle-replay console is out of scope (see Out of Scope) — recovery uses the
  existing idempotent manual triggers plus the abandon/resolve action.
- **FR-019**: Manual, on-demand triggering of each stage MUST remain available alongside automated
  scheduling and MUST be subject to the same idempotency and single-in-flight protections.

**Budget-aware automation**

- **FR-019a**: Each watchlist MUST carry an agency-configurable `budget_exceeded_policy` with values
  `continue` (default), `critical_only`, and `pause`, settable via a staff/admin endpoint. The default
  (`continue`) preserves today's behavior — the per-watchlist monthly budget remains advisory and does not
  stop automated work.
- **FR-019b**: When an automated cycle runs for a watchlist whose current-period spend is over its budget
  cap, the system MUST apply that watchlist's `budget_exceeded_policy`:
  `continue` → run the full cycle; `critical_only` → run expedited drafting for urgent/emergency findings
  but skip the routine end-of-cycle batch consolidation; `pause` → skip all automated LLM drafting for the
  cycle. Under every policy, serious-finding detection, severity bucketing, escalation, and operator
  alerting MUST still occur (Constitution III — a serious adverse-event MUST NOT be cost-suppressed), and
  manual/reviewer-triggered drafting MUST always be allowed to override. "Over budget" means the
  watchlist's accumulated spend for the **current UTC calendar month** (which resets at the month
  boundary, per the existing budget-usage model) has reached its `budget_amount` cap (the `exceeded`
  state, ≥100%), not the `warning` state.
- **FR-019c**: When a watchlist enters its budget `warning` (≥80%) or `exceeded` (≥100%) state, the system
  MUST record the transition as a domain event surfaced on the cost dashboard and the append-only audit
  log so the agency can act (raise the budget or change the policy). Active outbound notification delivery
  (email) is out of scope here and is performed by the delivery feature (spec 13).
- **FR-019d**: When an automated cycle skips drafting work due to a `critical_only`/`pause` policy, the
  skipped work and its reason MUST be recorded on the cycle and be operator-visible (not silently
  dropped); the operator can manually trigger the skipped drafting after raising the budget or changing
  the policy.

**Observability**

- **FR-020**: Job lifecycle transitions (enqueued, started, completed, retried, dead-lettered) MUST be
  observable via structured logs that bind the relevant client / run / finding identifiers and never log
  PII or secrets.
- **FR-021**: The admin dashboard MUST surface a failed-jobs / dead-letter view so managers/admins can
  see current job failures with enough context to investigate and re-trigger.

**Bootstrap & security**

- **FR-022**: The worker MUST load its secrets and validate its startup dependencies the same way the
  web application does, and MUST refuse to start if its datastore or broker is unreachable or a required
  artifact fails validation.
- **FR-023**: The broker connection MUST support a secure (TLS) transport in production and MUST be
  configurable (no hardcoded broker host); secrets/connection details come only from the existing
  secrets source.

**Eval gate (Constitution Principle IV)**

- **FR-025**: The system MUST ship a committed eval gate in `eval_thresholds.yaml`, enforced by the CI
  `eval` job, that scores a **due-selection golden set** (labeled fixtures of watchlists/cadences/clock →
  expected due set) at `precision = 1.0` and `recall = 1.0`, and asserts the reliability invariants
  `duplicate_rate = 0`, `loss_rate = 0`, `transient_retry_recovery = 1.0`, and
  `inline_vs_durable_parity = 1.0`. A regression below any committed threshold MUST block merge.

**Human-in-the-loop invariant (unchanged)**

- **FR-024**: This feature MUST NOT bypass or weaken the human-in-the-loop approval gate. Automated
  cycles may draft and consolidate reports, but a report still requires reviewer approval and nothing is
  sent or delivered as a result of automation. This invariant MUST be covered by an explicit regression
  test (an automated cycle never transitions a report to approved/sent).

### Key Entities *(include if feature involves data)*

- **Pipeline job**: a unit of durable work for one pipeline stage, identified by a deterministic logical
  key (run / finding+revision / report / watchlist-cycle) so re-enqueues and retries collapse to one
  execution. Carries enough context to reconstruct the work and attribute it to a client.
- **Watchlist cycle**: one record per automated monitoring cycle for a watchlist — watchlist, client,
  status (in-progress / completed / failed), current stage, start and completion timestamps, and links to
  that cycle's ingestion and index-build runs. Used to compute due-ness from the latest completed cycle,
  to detect an in-progress cycle (overlap guard), and to give operators cycle history.
- **Dead-letter record**: a durable record of a job that exhausted its retries — job type, target
  client, input digest, failure reason, attempt count, timestamps — used for operator visibility and
  audit, free of PII/secrets.
- **Scheduler tick**: the recurring scan that evaluates which watchlists are due and starts their
  cycles; idempotent with respect to in-progress cycles.
- **Budget-exceeded policy**: a per-watchlist setting (`continue` / `critical_only` / `pause`,
  default `continue`) chosen by the agency that governs how an automated cycle behaves when the
  watchlist is over its monthly budget cap. Never suppresses serious-finding detection/escalation.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of pipeline work triggered before a worker/web restart is completed after the restart
  (zero silent loss) in the reliability test suite.
- **SC-002**: Re-enqueuing or retrying any logical job produces exactly one set of persisted results
  (zero duplicate documents / findings / reports) across all stages.
- **SC-003**: Transient-failure jobs succeed without operator intervention after automatic retry;
  permanent-failure jobs are not retried — both demonstrated with a committed number in the test suite.
- **SC-004**: 100% of jobs that exhaust retries produce a dead-letter record **and** a corresponding
  append-only audit entry **and** appear on the admin dashboard failed-jobs surface.
- **SC-005**: On graceful shutdown, no in-flight job is lost or marked falsely complete; all such work
  is either finished or left re-runnable (verified in the shutdown-drain test).
- **SC-006**: The scheduler starts a cycle for exactly the set of due watchlists (active, non-empty,
  interval elapsed) and skips all others, with zero overlapping cycles for the same watchlist
  (verified by the cron due-selection test).
- **SC-007**: An automated cycle for a due watchlist advances through every stage to a consolidated
  batch report with no manual intervention (verified end-to-end).
- **SC-008**: Inline mode and durable mode produce identical persisted outcomes for the same inputs
  across all stages (parity test), and inline mode is provably unavailable in a production configuration.
- **SC-009**: No PII or secret appears in any job log, dead-letter record, or audit entry (verified by
  the redaction/no-PII assertions in the suite).
- **SC-010**: The full reliability + scheduling integration suite is the merge gate and passes in CI; any
  regression in these guarantees blocks merge.
- **SC-011**: A committed eval gate in `eval_thresholds.yaml` (CI `eval` job) holds at: due-selection
  `precision = 1.0` and `recall = 1.0` on the due-selection golden set; and reliability invariants
  `duplicate_rate = 0`, `loss_rate = 0`, `transient_retry_recovery = 1.0`, `inline_vs_durable_parity = 1.0`.
  Any regression below a committed threshold blocks merge (Constitution Principle IV).
- **SC-012**: Under every `budget_exceeded_policy`, an over-budget watchlist's automated cycle behaves as
  configured (`continue`/`critical_only`/`pause`) **and** never suppresses detection, escalation, or
  operator alerting of a serious (urgent/emergency) finding — verified by the budget-policy test set.

## Assumptions

- **Inline vs. durable as the parity mechanism.** "Inline mode" is a dev/test-and-local convenience that
  executes the *same* job functions synchronously; it exists so the existing integration suite and local
  development do not require a running worker/broker. Production is always durable. This satisfies
  "whichever is best for production" — production behavior is never inline.
- **Cron scope is the full cadence loop.** Per owner decision, the scheduler automates the complete
  per-watchlist cycle (ingestion through batch consolidation), not just ingestion. Manual triggers
  remain for all stages.
- **Dead-letter is surfaced in three places.** A durable dead-letter store, the append-only audit log
  (system-attributed), and a card on the existing admin dashboard. Audit attribution uses the existing
  system-actor mechanism so it does not pollute human-action semantics.
- **Cycle cadence is measured from cycle completion** (not from cycle start), so a slow cycle does not
  immediately re-trigger.
- **Reuse, don't rewrite.** Each existing stage runner keeps its current call shape and produces the
  same results; this feature changes orchestration (where/when/how-durably they run), not stage logic.
  **Exception:** the index-build step is extended to be watchlist-scoped (FR-014a) — this is a deliberate,
  scoped change to the prior index-build schema (add `watchlist_id`; per-(client, watchlist) single-running
  guard; watchlist-filtered document selection), required for clean per-cycle provenance. The exact
  constraint migration and full caller list MUST be pinned in `implementation-notes.md`.
- **Eval gate uses a reliability/scheduling golden set, not a model-quality golden set.** This is
  infrastructure, so there is no classifier/retrieval quality metric. Instead Constitution Principle IV is
  satisfied with committed thresholds in `eval_thresholds.yaml` (CI `eval` job): a **due-selection golden
  set** (`precision/recall = 1.0`) plus reliability invariants (`duplicate_rate = 0`, `loss_rate = 0`,
  `transient_retry_recovery = 1.0`, `inline_vs_durable_parity = 1.0`). See FR-025 and SC-011.
- **HITL and delivery untouched.** Automated cycles never send; reviewer approval is still required;
  delivery (sent/delivered statuses, notification routing) is explicitly a later feature.
- The existing secrets source, audit log, domain-event dispatcher, observability/cost tables, and admin
  dashboard from prior features are reused; the broker is the existing in-memory/Redis-class queue
  already adopted as the platform's execution model.

## Deferred to Planning

These are intentionally left to `/speckit-plan` (execution-model details that do not change the
functional contract above); they are recorded here so they are not silently omitted:

- **Scheduler topology** — whether the cron tick runs on a singleton scheduler or on every worker replica.
  The functional guarantee (no concurrent duplicate cycles, FR-017) holds regardless via idempotent cycle
  creation and the per-(client, watchlist) guard; the cron-coordination mechanism is a planning decision.
- **Worker concurrency & timeouts** — global max concurrent jobs, per-stage job timeouts, and the exact
  backoff schedule for the 3-try retry (FR-007). Bounded by FR-015c; specific numbers are planning config.

## Out of Scope

- Notification/SFTP delivery and `sent` / `delivered` / `delivery_failed` statuses (later delivery
  feature). Automation drafts and consolidates; it never sends.
- **Active outbound budget notifications** (emailing the agency when a watchlist nears/reaches its cap).
  Spec 11 records the budget-state transitions (events + dashboard + audit); the actual send is spec 13.
- Making the budget **warning threshold** configurable (e.g., 90% instead of 80%) — existing spec-3
  backlog item, not this feature.
- Guardrails, PII-redaction sweep, and database row-level security (separate security-hardening feature).
- Connection pooler (e.g., PgBouncer) introduction (deferred).
- A general operator job-management UI beyond the failed-jobs/dead-letter surface (e.g., pause/resume
  queues, per-job replay console) — record as a forward dependency if desired, not built here.
