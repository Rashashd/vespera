# SECURITY

Security posture for Pantera. Foundation-level controls are listed first; the application-layer
controls added by later specs and the security-audit remediation are summarized under "Application
controls" below. Deeper rationale lives in `DECISIONS.md` (Security Hardening + Security-Audit
Remediation), `RUNBOOK.md`, and `delivery-runbook.md`.

## Secrets

- All real secrets live only in Vault; fetched into memory at startup via `hvac`.
- No `.env` holds secrets; only `VAULT_ADDR` / `VAULT_TOKEN` are environment values.
- `gitleaks` runs pre-commit and in CI over the full history.

## Transport & edge

- Production Redis uses `rediss://` TLS.
- Security headers on every response: HSTS, `X-Frame-Options: DENY`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, CSP `default-src 'self'`.
- Auth endpoints are rate-limited to **5/min per source IP** (slowapi + Redis); there is no
  per-account lockout, by design (avoids an account-lockout denial-of-service vector).
- CORS origins are config-driven (`Settings.cors_allow_origins`); Bearer tokens, no cookies.

## Application controls (live)

The controls added by later specs and the security-audit remediation, in force today:

- **Multi-tenant isolation (defense in depth).** Every row is `client_id`-scoped at the repository
  AND RAG-retrieval layers, backed by Postgres **row-level security** (migration `0011`): the
  runtime connects as the least-privilege `pantera_app` role with per-transaction tenant context;
  an unset context is **default-deny** (breaks loud, never leaks).
- **Guardrails.** Every external-LLM call (triage, drafting agent) and document intake passes the
  torch-free guardrails sidecar (injection / jailbreak / topic-scope / cross-client rails). An
  outage fails safe — triage and the agent escalate, intake quarantines the document.
- **Egress redaction (Presidio).** PII/secrets are redacted before any external-LLM call, log,
  trace, or stored summary. The persisted report body stays full-fidelity (protected by RLS +
  Vault); the report delivered to its own client is the intended deliverable and is not redacted.
- **Human-in-the-loop send gate.** No report is delivered without a logged `reviewer` approval; the
  delivery job re-checks `approved` at send time so an edit/discard cancels the send.
- **Right-to-erasure.** `POST /clients/{id}/erase` (manager, exact-name confirm) purges a client's
  rows, chunk vectors, and user sessions, retaining only a PII-nulled tombstone + the audit log;
  the erasure is itself audited.
- **Reviewer comments redacted at rest.** Comments captured on edit-approve / reject are Presidio-
  redacted before they are persisted, so pasted PII never lands in the DB in the clear.
- **Kill-switches are test-only.** `guardrails_enabled` / `redaction_enabled` exist so tests can
  isolate behavior; the app refuses to boot with either disabled when `environment == production`.

## Logging

- Structured JSON via structlog with a redaction processor; secret/PII-named keys are never
  emitted. Sentry runs with `send_default_pii=False`.

## Audit

- Append-only `audit_log`, written atomically with each change; never auto-deleted.

## Startup validation

- The app refuses to boot if Vault, the database, or the cache is unreachable, if a required
  secret is missing, or if a model artifact mismatches — the scispaCy NER version or the embedder
  tokenizer SHA-256 (enforced; security-audit Cluster 2). The modelserver likewise refuses to
  serve on any artifact-hash mismatch.
- The app refuses to boot in `production` with the `guardrails_enabled` / `redaction_enabled`
  kill-switches disabled (security-boundary check).

<!-- Reporting a vulnerability: add a contact / disclosure policy before public release. -->
