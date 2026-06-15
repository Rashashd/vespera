# Phase 0 Research — Frontend SPA (Spec 010)

Decisions that resolve the spec's open technical questions, each grounded in the live codebase or an
explicit clarify decision. Format: **Decision / Rationale / Alternatives rejected**.

---

## R1. Frontend stack

**Decision**: React 18 + Vite 5 + TypeScript + Tailwind CSS + shadcn/ui. Routing via React Router 6.
Server state via TanStack Query (React Query) 5. Response validation via Zod. Component/integration
tests via Vitest + React Testing Library with MSW for API mocking; one e2e via Playwright.

**Rationale**: This is the stack named throughout the project memory and CLAUDE notes for the SPA.
Vite gives a fast dev server + a simple production build that a fresh-clone smoke test can run
(`npm ci && npm run build`). React Query directly satisfies FR-026 (loading/error/empty states),
FR-017 (refetch-on-conflict), and the "reload/refetch for freshness, no websockets" assumption.
shadcn/ui (Radix-based) gives accessible primitives + keyboard/focus support for the limited a11y
scope in FR-028 without a heavy component framework. Zod lets the UI parse the **loosely-typed**
backend payloads (`corroboration_sources: list[dict]`, `structured_fields` as a claim list) defensively.

**Alternatives rejected**: Next.js (SSR/server runtime unneeded — the backend is the API; a static
SPA is leaner per Principle VI). Redux (React Query covers server state; a tiny React context covers
auth + acting-client — Redux is unjustified complexity). CRA (deprecated/slow vs Vite).

## R2. Auth token storage

**Decision**: Store the JWT access token in `localStorage`; restore it on app init; attach as
`Authorization: Bearer` on every request. On a 401/expired response, clear it and route to sign-in.
Acting-client selection also persisted in `localStorage` (per-device, per FR-004a).

**Rationale**: The backend issues a single ~8h bearer access token with **no refresh token**
(`Settings.auth_token_ttl_seconds = 28800`, confirmed in `app/core/config.py`). FR-003 requires the
session to survive a page reload — in-memory-only storage cannot. Header bearer auth (not cookies)
means `localStorage` is the pragmatic choice; the XSS exposure is mitigated by the
constitution-mandated CSP/security-headers middleware and the short token life. A cookie scheme would
require backend `Set-Cookie`/CSRF changes that are out of scope.

**Alternatives rejected**: In-memory only (fails reload persistence FR-003). HttpOnly cookie
(backend change, CSRF surface, out of scope). Refresh-token rotation (no refresh token exists — it's
a recorded future dependency in the forward-dependency ledger).

## R3. Passage-text endpoint (FR-029)

**Decision**: Add `GET /clients/{client_id}/passages/{chunk_id}` returning the chunk's exact `text`
plus source metadata (document title, external_id, date, source_reliability). Client-scoped via
`Chunk.client_id == client.id`; 404 → `{detail: "PASSAGE_UNAVAILABLE"}` when the chunk doesn't exist
or isn't this client's.

**Rationale**: A claim's `source_ref` **is a stringified `chunks.id`** — verified in
`app/agent/tools.py` (`draft_report` sets `source_ref=c.source_ref` where the LLM passes chunk_ids
from `retrieve`, and `_validate_chunk_refs` validates them against `Chunk.id`/`Chunk.client_id`).
`corroboration_sources` items (shape = `app/rag/schemas.py:CorroborationSource`) carry
`passage_chunk_ids: list[int]`. So resolving a citation to its passage is a single `Chunk` lookup +
a join to `documents` for title/external_id. The `chunks` table (`app/embedding/models.py:Chunk`)
holds `text`, `section`, `source_reliability`, `date`, `document_id`. This is the only missing piece
for "clickable to exact passage."

**Alternatives rejected**: Embedding passage text inside `ReportResponse` (bloats every report
payload with full chunk text the reviewer may never open; the on-demand endpoint is leaner). A batch
"resolve many chunk_ids" endpoint (nice-to-have; single-id keeps v1 simple — the UI fetches on click).

## R4. Client-portal read path (FR-030) + per-report findings (FR-031)

**Decision**: New `app/reports/portal_routes.py` exposing:
- `GET /clients/{client_id}/portal/reports?watchlist_id=` — own-client reports with
  `status ∈ {approved, sent, delivered}` only, grouped/filterable by watchlist; returns a
  portal-safe summary (no reviewer-internal fields).
- `GET /clients/{client_id}/portal/reports/{report_id}` — read-only detail, same status filter.
- `GET /clients/{client_id}/reports/{report_id}/findings` — a report's constituent findings
  (drug, reaction, bucket, per-report `state`), client-scoped, authorized like the parent report
  (used by the batch drop/discard UI **and** the portal finding-status display).

All guarded by `current_active_principal` + `acting_client(allow_suspended=True)` for reads. The
existing reviewer queue/detail routes (`require_reviewer`) are **NOT** widened (FR-030 mandate).

**Rationale**: `acting_client` already enforces that a client-user may only name **their own**
`client_id` (verified in `app/auth/dependencies.py` — client-users get 404 on any other client). So
a client-scoped route guarded by it is automatically safe for client-users, while staff can also read
it for the acting client. The status filter is applied in the query (`Report.status.in_([...])`).
Per-report findings come from `ReportFinding` (join `Finding` for drug/reaction/bucket) — the
`ReportFindingResponse` schema exists in `app/reports/schemas.py` but is **unexposed** and lacks
drug/reaction/bucket, so we add a richer `ReportFindingDetail` schema.

**Alternatives rejected**: A brand-new client-user-only auth dependency (unnecessary —
`acting_client` already does own-client gating for `UserType.CLIENT`). Reusing the reviewer route
with a role branch (FR-030 explicitly forbids widening the reviewer routes; keep portal reads
separate and minimal).

## R5. Reviewer all-reports view (FR-006a)

**Decision**: Extend the existing `GET /clients/{id}/reports` (in `app/reports/routes.py`) to accept
`status=all` (or any concrete status) so reviewers can list every status, while the default (no
`status`) keeps returning only the review states (`drafted/under_review/needs_manual_revision`).

**Rationale**: The route already takes a `status` query param and is `require_reviewer`. Today an
explicit `status=` filters to one value and the no-arg default filters to `_REVIEW_STATUSES`. Adding
an `all` sentinel (skip the status `where`) is a ~3-line change that yields the read-only history view
without a new route or widening access. The frontend's "action queue" uses the default; the
"all reports" tab passes `status=all` (and can pass a concrete status for filtering).

**Alternatives rejected**: A separate `/reports/all` route (duplicates the handler for no benefit).
Removing the default review-status filter (would break the existing reviewer queue contract).

## R6. Cost attribution store (FR-033)

**Decision**: New table `llm_usage` (migration `0009`) + `app/observability/` package. One row per
external LLM call: `client_id`, nullable `finding_id`, `model`, `input_tokens`, `output_tokens`,
`cost_usd` (numeric), `call_site` (`triage|agent`), `created_at`. Written by a best-effort
`record_usage()` helper that catches and logs on failure (never propagates — FR-033). The cost
dashboard (`GET /clients/{id}/usage`) aggregates per client from this table only (FR-034).

**Rationale**: No prior cost backend exists. The agent already computes `usage_metadata.total_tokens`
per turn in `app/agent/graph.py:agent_node`; LangChain's `usage_metadata` also exposes
`input_tokens`/`output_tokens`, so capturing both at that site is a small addition. The triage call
in `app/triage/llm.py:_call_llm` returns the raw provider JSON — the Anthropic response carries
`usage.input_tokens`/`usage.output_tokens`; the OpenAI response carries `usage.prompt_tokens`/
`completion_tokens` — so token capture is available at that site too. Cost = tokens × pinned
per-model price from `Settings`. Numeric/decimal storage avoids float rounding so SC-011 (dashboard
total reconciles with summed records) holds.

**Alternatives rejected**: Reading costs from the LangSmith API at view-time (FR-034 forbids — the
dashboard must work even if LangSmith is unreachable). Deriving cost in the frontend (pricing is
config that belongs server-side; keeps a single source of truth).

## R7. LangSmith tracing (FR-032)

**Decision**: Enable LangSmith tracing via the standard env vars set from config at startup
(`LANGCHAIN_TRACING_V2=true`, `LANGCHAIN_API_KEY=<vault secret>`, `LANGCHAIN_PROJECT=pantera`) —
**only when the key is configured** (empty key ⇒ tracing disabled, app still boots). The LangGraph
agent traces automatically (it uses LangChain chat models). The triage call bypasses LangChain
(raw httpx in `app/triage/llm.py`), so wrap `_call_llm` (or `resolve_yes_no`/`assess_valence`) with
`langsmith.traceable` to capture it. Tag every trace/usage row with `client_id` and, where available,
`finding_id`.

**Rationale**: The agent path is built on `langchain_anthropic.ChatAnthropic` /
`langchain_openai.ChatOpenAI` (`app/agent/llm_binding.py`), which emit LangSmith traces with zero
code change once the env vars are present. The triage path is the documented exception that "bypasses
LangChain and MUST be instrumented explicitly" (clarify Q5 + FR-032). `langsmith` is added to the
main dependency group. Locally-run ONNX models (classifier/embedder via modelserver) make no external
call and are excluded (FR-032).

**Alternatives rejected**: Langfuse/OTel (LangSmith is the named tool and integrates natively with
the existing LangChain agent). Making tracing mandatory at boot (would force the key into
`_REQUIRED_SECRETS` + ci.yml; best-effort tracing keeps fresh-clone/CI green without the secret).

## R8. Config & secrets placement (FR-035)

**Decision**: Add to `app/core/config.py:Settings`: `langsmith_api_key: str = ""` (secret, from
Vault, **optional** — not in `_REQUIRED_SECRETS`), `langsmith_project: str = "pantera"`,
`tracing_enabled: bool` (derived/explicit), and a per-model pricing map, e.g.
`llm_price_per_1k_input` / `llm_price_per_1k_output` keyed by the pinned model names
(`anthropic_model`, `openai_model`), with the **unit (per-1K-tokens) and currency (USD)** documented
in the field comments. Pricing is non-secret config; the key is the only secret.

**Rationale**: Constitution config discipline — secrets only in Vault, non-secret config in
`Settings` with `extra="forbid"`, no `os.getenv()` outside config. CHK015/CHK028 require the pricing
unit + currency to be unambiguous; encode them in the field names/comments.

**Alternatives rejected**: Pricing in `eval_thresholds.yaml` (that file is for eval gates, not
runtime config — the anti-hallucination rule explicitly says runtime config → `Settings`).
Hardcoding prices in `pricing.py` (violates "no magic config outside `Settings`").

## R9. Queue ordering & SLA (FR-007)

**Decision**: Backend returns reports `created_at desc` (unchanged). The frontend sorts
**expedited-first**, then by `sla_deadline` ascending (soonest/overdue first) among expedited, then
`created_at` as the final tie-break; it renders the SLA countdown (incl. an overdue state) from
`sla_deadline`. Pagination via the existing `limit`/`offset` query params.

**Rationale**: `ReportSummary` carries `report_type` and `sla_deadline` (verified in
`app/reports/schemas.py`), so the UI has everything to sort/countdown client-side — no backend
ordering change needed. The existing route already supports `limit` (≤200) + `offset`.

**Alternatives rejected**: Server-side composite ordering (more backend change for a pure
presentation concern the spec already designates a UI responsibility).

## R10. Delivery status display (FR-006b) — forward dependency

**Decision**: The UI computes a **delivery status** label per report: while the live `ReportStatus`
ends at `approved`, an approved report displays **"Approved (pending delivery)"**; the UI is built to
render **Sent / Delivered / Delivery-failed** + `delivered_at` once spec 13 introduces and sets those
states. Client portal visibility includes `status ∈ {approved, sent, delivered}` so it is populated
by `approved` now.

**Rationale**: Confirmed against `app/reports/enums.py:ReportStatus` =
`drafted|under_review|approved|rejected|discarded|needs_manual_revision` — **no sent/delivered/
delivery_failed**. This is the recorded spec-13 forward dependency (ledger + spec.md Assumptions). The
frontend treats unknown/forthcoming statuses as "pending delivery" so it degrades gracefully and
lights up automatically when spec 13 adds them.

**Alternatives rejected**: Adding the `sent`/`delivery_failed` enum values in spec 10 (rejected by
the product owner's scoping — display-only now; spec 13 owns the states + the actual send).

## R11. Testing strategy (SC-010)

**Decision**: Component/integration tests (Vitest + RTL + MSW mocked API) across all primary surfaces
(sign-in, reviewer queue, report detail incl. citation→passage, admin console, client portal);
**one** Playwright e2e for the reviewer approve/reject happy path against the running stack. The three
new backend endpoints + usage capture are covered by `pytest` under existing gates (95% HITL backend).
The fresh-clone smoke test is extended to `npm ci && npm run build` and serve the SPA (SC-009).

**Rationale**: Matches clarify Q4 ("product-worthy" = breadth via mocked component tests + one real
e2e). Keeps the e2e suite cheap/stable while proving the critical safety path end-to-end.

**Alternatives rejected**: Full e2e coverage of every flow (slow/flaky for little marginal safety
value). No e2e at all (the HITL happy path is the product's core control — it warrants one real
browser test).
