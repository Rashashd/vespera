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
- **Startup SHA-256 validation refuses boot** — prevents serving from a partial or tampered
  artifact set; refuse-boot is non-negotiable (FR-010/D4). Secrets from Vault via hvac (D5).
- **Lean image via uv group isolation** — `uv sync --only-group modelserver --no-install-project`
  installs only the 9-package serving set; torch/transformers live in `training` group (offline
  only). Target < 500 MB (D1).
- **Eval gate at macro-F1 ≥ 0.80** — `eval_thresholds.yaml` + `modelserver/eval/run_eval.py`
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
