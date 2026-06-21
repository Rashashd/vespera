# DECISIONS

Architecture and model decisions, with the numbers that justify them. Per-feature design
rationale lives in each `specs/<feature>/research.md`; this file records project-level
decisions defended on demo day.

## Foundation (001-platform-foundation)

- **Secrets in Vault only** — fetched at startup via `hvac`; no `.env` for secrets.
- **Atomic audit** — audit rows are written in the same transaction as the change they
  record; a failed audit write rolls back the operation.
- **Reserved system actor** — `actor_id = 0`, `actor_type = 'system'`; keeps the audit log
  decoupled from the (later) users table while guaranteeing a non-null actor.
- **Shallow public health endpoint** — liveness only, to avoid restart storms.

## Auth & Roles (002-auth-and-roles)

Full rationale in `specs/002-auth-and-roles/research.md` (D1–D13). Project-level highlights:

- **fastapi-users for auth** — vetted async JWT + argon2 hashing; safer than hand-rolling
  crypto. Used for the read path (token validation, `current_active_user`) and JWT issuance.
- **Writes are manual within the request transaction** — fastapi-users' DB adapter commits
  internally, which would break the foundation's atomic-audit guarantee, so user create/update
  is done directly on the `get_session` transaction and the audit event is dispatched in the
  same transaction.
- **Stateless JWT, ~30 min, no refresh** — deactivation takes effect within ≤1 token lifetime;
  no session store to revoke.
- **Two roles, transparent guards** — `admin`/`reviewer` via a `require_role` dependency
  (401 unauthenticated vs 403 forbidden); the `reviewer` send-authority is declared here and
  exercised by the later HITL spec.
- **Audit human-actor FK** — a new nullable `audit_log.actor_user_id` → `users.id`; the
  system sentinel (`actor_id = 0`) stays unlinked, preserving the foundation's audit behavior.
- **Account email is intentionally stored in `UserLoggedIn`/`LoginFailed` audit payloads**
  (analyze finding L1, signed off 2026-06-06): it is an account identifier — not patient PII —
  and is required for credential-stuffing / forensic investigation. Passwords and hashes are
  never stored or logged.
- **Bootstrap email must use a deliverable domain** — `UserRead.email` is `EmailStr`, which
  rejects reserved TLDs (e.g. `.local`) on read-back; the seed default is `admin@pantera.io`.
- **Login rate limit 5/min/IP (no account lockout)** — per-IP throttling avoids an
  account-lockout denial-of-service vector.

## Literature Ingestion (004-literature-ingestion)

Full rationale in `specs/004-literature-ingestion/research.md` (D1–D16). Highlights:

- **In-process BackgroundTasks (not ARQ)** — spec 11 adds durable scheduling; using
  BackgroundTasks now avoids a premature dependency and keeps the worker spec-11 only.
- **Cross-source dedup by normalized external ID** — `doi:<x>` > `pmid:<x>` > `<source>:<id>`;
  lowercased + stripped so the same paper matches regardless of how adapters report it.
- **Source reliability tiers** — `regulatory_alert(3) > peer_reviewed(2) > preprint(1) >
  case_report(0)`; a document's tier is recomputed as `max(rank)` across all contributing sources
  on each dedup hit, so the highest-confidence source wins.
- **Watermarks per (watchlist, source)** — only advanced on source success; first run uses a
  configurable lookback window (default 365 days). Missing watermark → use lookback.
- **Optional API keys** — `pubmed_api_key`/`openfda_api_key` are NOT in `_REQUIRED_SECRETS`;
  adapters fall back to the public rate-limited tier. This avoids a CI change per spec.
- **Bundled slim MeSH list** — ~120 headings from NLM 2024; validated at write time via
  `importlib.resources`; missing artifact degrades to `unvalidated` (non-fatal). The runner
  excludes confirmed-invalid terms from PubMed MeSH targeting.
- **Per-source semaphore** — 3 concurrent requests per source; prevents hammering public APIs.
- **No raw payload / PII in logs** — FAERS `patient` field is stripped at parse time; structlog
  only binds `client_id`/`run_id`.

## Modelserver — Adverse-Event Classifier & Medical Embedder (005-modelserver)

Full rationale in `specs/005-modelserver/research.md` (D1–D16).

- **Classical TF-IDF + LR selected over PubMedBERT/LLM zero-shot** — three candidates evaluated
  on a held-out ADE Corpus-style set (12 examples, disjoint from training):
  TF-IDF+LR = 0.91 macro-F1, PubMedBERT ONNX ~0.78 (below gate), LLM zero-shot ~0.83
  (external API dependency rejected per D7). Classical pipeline wins on F1, simplicity, and
  image-size neutrality. Artifacts in `modelserver/models/MODEL_CARD.md`.
- **0.5 default cutoff, caller-owned policy** — the server returns raw `confidence ∈ [0,1]`;
  `is_adverse` at 0.5 is a convenience default. Real policy (triage threshold, FP/FN trade-off)
  is owned by the calling spec (Spec 6 / guardrails). Locked in D2.
- **Stateless, no DB** — modelserver holds no mutable state; all inference is ephemeral.
  Restartable with zero migration burden. Locked in D7.
- **Startup SHA-256 validation refuses boot** — the modelserver validates its served ONNX
  artifacts (classifier/embedder/tokenizer) against `manifest.json` and refuses to start on any
  mismatch or missing/partial artifact (`modelserver/core/startup.validate_artifacts`, FR-010/D4).
  The *app* side (Cluster 2 / H1) likewise boot-validates the artifacts it loads in-process — the
  scispaCy NER model (pinned package version) and the embedder tokenizer (SHA-256) — via
  `app/core/startup.check_model_artifacts`, and pin-checks the modelserver's reported model
  versions (embedder/classifier/reranker) at index time (`verify_served_model_versions`). Each
  component validates what it loads; refuse-boot is non-negotiable. Secrets from Vault via hvac (D5).
- **Lean image via uv group isolation** — `uv sync --only-group modelserver --no-install-project`
  installs only the 9-package serving set; torch/transformers live in `training` group (offline
  only). Target < 500 MB (D1).
- **Eval gate at macro-F1 ≥ 0.80** — `eval_thresholds.yaml` + `eval/classifier/run_eval.py`
  block merges that regress classifier quality; runs in its own lean CI job (D10/FR-013).
- **768-dim L2-normalised embeddings** — output shape fixed for downstream cosine search;
  mean-pool with attention-mask weighting; normalised to unit sphere so dot-product = cosine
  (D3/FR-002). Quantize the embedder for production to stay lean (D15).

## Parse, Chunk & Embed — RAG Index Build (006-parse-chunk-embed)

Full rationale in `specs/006-parse-chunk-embed/research.md` (D1–D12).

- **HNSW vector index over IVFFlat** — no training-on-empty-table overhead; incremental corpus
  growth does not degrade recall. IVFFlat `lists` tuning and re-training across growing corpus
  rejected. HNSW default `m=16, ef_construction=64` sufficient for Pantera scale (D1).
- **Exact tokenizer-based chunking** — chunks counted with embedder's own tokenizer.json
  (not LLM-style BPE assumptions). Hard cap at 512 tokens prevents silent truncation by the
  embedder; boundary computed before embedding so no wasted API calls (FR-025/D6).
- **Chunk target ~256 tokens, ~15% overlap** — balance: small chunks → more vectors to search
  but finer granularity; overlap → continuity across span boundaries (D6/FR-008).
- **Seven source parsers, one protocol** — PubMed/Europe PMC JATS XML via lxml; OpenFDA
  FAERS/Label JSON; FDA MedWatch/EMA/MHRA regulatory feed. Each source has a single parser
  instance; dispatch by source name via a registry. Unknown sources → permanent error (no retry).
- **Source selection: reliability → richness → recency** — multi-source documents parse from
  exactly one payload (highest rank tier, then longest, then newest). Never merge across sources
  (determinism / auditability) (D8/FR-024).
- **In-process index build via BackgroundTasks** — mirrors spec 4 ingestion pattern.
  Atomic commit (chunks + state) within one transaction. Prevents half-indexed documents on crash.
  One in-flight build per client enforced by partial-unique index (FR-026/FR-028).
- **Idempotency + incremental via state machine** — document states: `not_indexed` →
  (success) → `indexed` | (parse failure) → `errored_permanent` | (transient) → `errored_transient`.
  Re-runs skip `indexed`, `indexed_empty`, `errored_permanent`. Retry `errored_transient`.
  Active watchlist filter: exclude documents linked only to inactive watchlists (FR-020).
- **Lexical leg: generated tsvector + GIN index** — `to_tsvector('english', text)` as STORED
  column; automatic drift-prevention. Pair with dense vectors for hybrid retrieval (Spec 7).
  drug column always NULL in v1; populated by Spec 8 NER (FR-023).
- **PII-free logging** — never log chunk text, FAERS patient fields. Bind only `client_id`,
  `run_id`, `document_id` for troubleshooting (FR-019/SC-007).
- **Manager/admin-only trigger, staff-readable status** — `require_admin` guard on POST /index;
  reviewer and client-user → 403 (FR-027/SC-013). GET endpoints via `acting_client_read`
  (staff any role, or owning client-user).

## Triage & Routing (008-triage-routing)

Full rationale in `specs/008-triage-routing/research.md` (D1–D8). Project-level highlights:

- **scispaCy BC5CDR for NER** (D1) — `en_ner_bc5cdr_md` runs as a module-level singleton
  (`@lru_cache`). CHEMICAL entities = watchlist drugs; DISEASE entities = reactions. No same-sentence
  DISEASE + drug in title/summary → incidental; filtered before classification (US2). The
  `en_ner_bc5cdr_md` model is in main project deps (not the no-torch modelserver group); it is
  CPU-bound and off-loaded via `asyncio.to_thread`.
- **Three-stage classify (D3)** — confidence ≥ `Settings.triage_confidence_threshold` (0.70) → trust
  model; below → LLM resolve; LLM failure → escalate=YES (fail-safe). Raw `confidence` is used for
  re-thresholding, not `is_adverse` (which reflects the modelserver's internal 0.50 cutoff).
- **First real outbound LLM call (D3)** — `LLMClient` was only a config handle (provider/model/api_key);
  spec 8 builds the HTTP call from scratch (`httpx.AsyncClient` + tenacity retry). Branches on
  `llm.provider`: Anthropic (`POST /v1/messages`) and OpenAI (`POST /v1/chat/completions`). Structured
  JSON output validated with Pydantic. Retry on timeout/network only — never on 4xx.
- **Injection hardening (Constitution Principle II)** — LLM prompts frame the document as untrusted
  data; a planted-instruction golden-set case is CI-gated. Full guardrails (NeMo) sequenced to spec 12.
  **✅ CLOSED by spec 12:** the torch-free guardrails sidecar now wraps both triage egress sites
  (input+output rails), CI-gated by the red-team gate (block-rate=1.0). See Security Hardening below.
- **LLM call precedes Presidio redaction (documented deviation)** — the corpus is public literature;
  logs bind IDs only. Sequenced to close in spec 12 with the broader Presidio sweep.
  **✅ CLOSED by spec 12:** Presidio redaction now runs before the triage LLM call (FR-012).
- **Confidence threshold in Settings, NOT eval_thresholds.yaml** — `eval_thresholds.yaml` is read
  only by CI eval scripts (`recall_min`, `precision_min`). Runtime knobs always go in `Settings`.
- **In-process triage trigger (D2)** — fires immediately after `INDEXED` success in the embedding
  runner. Durable ARQ job wrapping is spec 11. A triage failure never rolls back a successful embed.
- **Failure matrix (FR-018)** — classifier/DB failure → no finding (retry), emit `triage.operator_alert`
  ERROR; LLM failure → finding via fail-safe (escalate / `positive`). Asymmetry is intentional:
  classifier failure means we cannot decide safely; LLM failure is a refinement step only.
- **ICH E2E keyword artifact** (D5) — versioned dict in `app/triage/keywords/ich_seriousness.py`;
  per-client custom keywords escalate-only via `max(rank)` (FR-004). Regulatory-alert floor
  (`source_reliability == "regulatory_alert"` → min URGENT) applies to YES verdicts only.
- **Staleness sweep (SC-001)** — `app/triage/sweep.py` finds INDEXED docs with zero findings older
  than `Settings.triage_staleness_max_age_minutes`; emits `triage.operator_alert` (stage=sweep).
  Routing to paging/remediation is spec 11.

## Security Hardening (012-security-hardening)

Three independent layers harden the existing pipeline; the two spec-8 triage deviations are closed.

- **Guardrails sidecar — purpose-built, torch-free, no per-call LLM (Constitution VI).** The literal
  `nemoguardrails` package pulls torch and a per-call LLM, which violates the no-torch serving
  constraint and the deterministic-CI-gate requirement. We ship a lean top-level `guardrails/`
  FastAPI sidecar (mirrors `modelserver/`) with a heuristic regex/keyword rails engine
  (injection / jailbreak / topic-scope / cross-client), `POST /guard` + `GET /health`,
  `X-Service-Token`. Determinism makes the red-team gate stable. **Justified deviation** from the
  literal library, satisfying the same `/guard` contract. PII is NOT a rail (Presidio owns it).
- **Rails per direction** — input checks all four rails; output checks injection-echo + topic-scope +
  cross-client (jailbreak is input-only). First blocking rail short-circuits; a rule-engine error
  fails safe to `block`/`rail_engine_error` inside the sidecar (never 5xx).
- **Fail-safe by call site** — guardrails block/outage → triage escalates, agent escalates, intake
  quarantines (`DocumentQuarantined`, cycle continues). `GuardrailRefused`/`GuardrailUnavailable`
  audited with reason codes only (never document text).
- **Redaction is in-process, egress-only (Presidio).** `app/redaction/` runs in the app + worker (no
  new container — Presidio is a library). Applied before every external-LLM call / log / trace /
  derived summary; the persisted report body/findings/chunks stay full-fidelity (DB protected by RLS
  + Vault). Uses `en_core_web_sm` (torch-free) for PII NER — **NOT** scispaCy `en_ner_bc5cdr_md`
  (a biomedical NER, not PII) — plus custom SECRET / MEDICAL_RECORD / US_SSN recognizers. Logs/traces
  use a fast spaCy-free regex scrubber (`scrub_text`) to avoid blocking the event loop.
- **RLS two-role design.** Runtime connects as a new least-privilege `pantera_app` role
  (`app_database_url`, NOBYPASSRLS, `statement_cache_size=0` for PgBouncer-forward); migrations/seed
  keep the privileged `pantera` role (`database_url`). Migration 0011 applies FORCE RLS +
  role-aware `tenant_isolation` policies on all 21 `client_id` tables (`clients` keys on `id`);
  `users`/`audit_log` are documented exemptions (login resolves the user pre-context; identity
  isolation stays at the app layer). Context is per-transaction via `set_config(...,true)`; **unset =
  default-deny** (breaks loud, never leaks). The role is created at DB bootstrap, NOT in the migration.
- **Kill-switches are test-only.** `guardrails_enabled`/`redaction_enabled` exist so tests can isolate
  behaviour; `app/core/startup.check_security_boundary` refuses to boot if either is `False` when
  `environment == "production"` (FR-003/FR-014a).
- **Tracing re-enablable.** With redaction at the agent egress, the LangSmith trace carries only
  redacted content ("redaction is the control", FR-024). Default stays OFF; flip on in non-prod to
  verify (SC-007).
- **CI gates added** — `eval_thresholds.yaml security:` (redaction leak=0; red-team block-rate=1.0,
  false-refusal=0). The red-team gate imports the rails engine directly, so no sidecar runs in CI.

## Report Delivery & Notifications (013-delivery)

Full rationale in `specs/013-delivery/research.md`; operational detail in `delivery-runbook.md`.
Project-level highlights:

- **Delivery is gated by the HITL approval, enforced at send time.** A passive `ReportApproved`
  handler enqueues the durable `task_deliver_report`; the job **re-checks the report is still
  `approved` at send time** before dispatching, so an edit/discard between approval and send
  cancels delivery. The HITL gate (Constitution I) is therefore enforced again at the delivery
  boundary, not just at the queue.
- **Report status is derived, not stored.** Overall delivery status is computed from the
  `delivery_attempt` rows: `delivered` = all channels delivered; `delivery_failed` = any channel
  failed; otherwise `sent`. There is no separate status enum to drift out of sync with the attempts.
- **A report with no deliverable path is *held*, not *failed*.** No configured channel, or a
  suspended client, leaves the report `approved` and alerts staff; reactivating the client (or a
  staff `resend`) re-enqueues delivery. Failure is reserved for an actual channel/callback failure,
  so the dashboard never shows a spurious red for an unconfigured client. (This graceful-hold path
  is the `fix/portal-detail-delivery-hold` work.)
- **The SFTP credential lives in n8n, never in the app DB.** The app stores destination metadata
  only (`sftp_host`/`sftp_path`); n8n holds the secret and performs the transfer. This keeps a
  whole class of delivery secret out of the application trust boundary.
- **n8n routes delivery/notifications; ARQ executes pipeline work — neither replaces the other**
  (Constitution VI). Backend → n8n is one webhook per channel (httpx + tenacity, 3 attempts, never
  retries 4xx); n8n → backend is a callback `POST …/delivery-callback` authenticated by a
  constant-time `X-Delivery-Token` (service token, bypasses user JWT, sets per-client RLS context
  explicitly), idempotent per `(report, channel)`. No extra message broker is introduced.
- **Delivery config is optional and fail-soft.** `n8n_webhook_url` and `delivery_callback_token`
  are NOT in `_REQUIRED_SECRETS`; unset → the app boots and **holds** delivery (a missing/empty
  callback token rejects callbacks with 401, so it must be set in CI even though it is optional).
- **The delivered report body is NOT redacted — it is the deliverable.** Redaction is egress-only
  for external-LLM/log/trace paths; a client's own approved report is rendered full-fidelity and
  sent to that client. Delivery/notification **logs and traces** are PII-free (Presidio /
  `scrub_text`); failure `error`/`reason` strings are scrubbed before they are logged or persisted.
- **SLA sweep, two independent timers** (`task_delivery_sla_sweep`, cron): a `sent` report with no
  callback within `delivery_no_callback_window_hours` (default 6) → `delivery_failed` + staff alert;
  an open expedited report past `sla_deadline` escalates Tier-1 (the client's reviewers), then
  Tier-2 (manager/admin) after `sla_tier2_interval_hours`. Each tier fires at most once; an actioned
  report never escalates. Budget-threshold notifications dedup by state (one alert per crossing).

## Security-Audit Remediation (post-spec hardening)

A security/safety audit run after the 13 specs surfaced one CRITICAL plus several HIGH/medium
issues; they are being remediated cluster-by-cluster (each its own PR). Decisions worth recording
at the project level — clusters 1–3 are complete (migrations `0013`–`0015`):

- **Triage now fails safe — proven by construction (Cluster 1, Constitution III).** A classifier
  or NER outage previously returned `None` and let the cycle complete *clean*, silently suppressing
  detection. It now **escalates** (forces `verdict=YES`, `resolution_path="escalated"`) on a
  classifier outage and emits an operator alert on an NER outage; a document that could not be
  triaged writes a durable `triage_failed_at` marker, and consolidation marks the cycle **`degraded`**
  (`status=completed` + `degraded_reason`, so the partial report still ships) — a broken run can
  never report clean. `findings.classifier_version` (the classifier artifact SHA) is recorded;
  **NULL distinguishes an outage escalation from a low-confidence one**. The backstop staleness
  sweep was dead code; it is now wired to cron and **remediates** (re-triages slipped documents,
  re-enqueues orphaned expedited findings). Migrations `0013` (markers + version) and `0014`
  (`triaged_at`, so the sweep tells a legitimately-zero document from a never-triaged one).
- **Model integrity refuses boot on a bad artifact (Cluster 2).** App-local boot validation now
  refuses to start on a scispaCy NER version mismatch or embedder-tokenizer SHA mismatch (mirroring
  the modelserver's own refuse-boot), and the index-time `/ready` pin-check is extended to the
  classifier and reranker. The onnx 1.19.0 path-traversal/TOCTOU CVEs were cleared by pinning
  `onnx>=1.21.0` and `requires-python ">=3.12,<3.13"` — **the project is now Python 3.12-only.**
- **Right-to-erasure + reviewer-comment redaction at rest (Cluster 3, Constitution V).** A manager
  can `POST /clients/{id}/erase` (the body must echo the client's exact name as a safeguard); it
  atomically purges every `client_id` table — **including chunk vectors and user sessions** — and
  retains only a minimal `clients` tombstone (id + name + timestamps kept, PII nulled,
  `status=erased`, `erased_at` set) plus the PII-free `audit_log`, dispatching `ClientErased`. The
  erasure is itself audited and atomic with the audit row. Separately, reviewer comments are now
  redacted (Presidio `redact_async`) **before they are persisted** on edit-approve and reject, so
  PII a reviewer pastes never lands in the DB in the clear. Migration `0015`.
- **PII → external-LLM sufficiency is a human regulatory call, deliberately NOT pre-built.**
  Patient-derived free-text literature reaches the external LLM after *best-effort* Presidio
  redaction; whether that satisfies GDPR/HIPAA/ICH is a regulatory judgment routed to a human and a
  **do-not-ship-to-real-data gate**, not a coding task. Flagged, not speculatively engineered.
