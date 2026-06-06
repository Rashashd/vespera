# SECURITY

Security posture for Pantera. Foundation-level controls are listed here; feature specs add
their own (guardrails, redaction, HITL gate, erasure).

## Secrets

- All real secrets live only in Vault; fetched into memory at startup via `hvac`.
- No `.env` holds secrets; only `VAULT_ADDR` / `VAULT_TOKEN` are environment values.
- `gitleaks` runs pre-commit and in CI over the full history.

## Transport & edge

- Production Redis uses `rediss://` TLS.
- Security headers on every response: HSTS, `X-Frame-Options: DENY`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, CSP `default-src 'self'`.
- Auth endpoints will be rate-limited (slowapi capability is in place; policy lands with auth).

## Logging

- Structured JSON via structlog with a redaction processor; secret/PII-named keys are never
  emitted. Sentry runs with `send_default_pii=False`.

## Audit

- Append-only `audit_log`, written atomically with each change; never auto-deleted.

## Startup validation

- The app refuses to boot if Vault, the database, or the cache is unreachable, or if a model
  artifact hash mismatches (enforced once artifacts exist).

<!-- Reporting a vulnerability: add a contact / disclosure policy before public release. -->
