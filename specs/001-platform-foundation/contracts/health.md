# Contract: Health Endpoint

The only externally exposed interface in this feature. Used by the hosting platform's
liveness probe.

## `GET /health`

- **Auth**: none (public, unauthenticated) — FR-007
- **Depth**: shallow liveness only; MUST NOT check database or cache per call
- **Availability**: only routable after lifespan startup completes successfully; before that
  the application is not serving (connection refused / not yet routable), never a false-OK

### Response — 200 OK

```json
{ "status": "ok" }
```

- Body contains only a bare status — no version, dependency state, or build info
  (minimal-disclosure, FR-007)
- `Content-Type: application/json`
- Standard security headers present on the response (see below)

### Security headers (on this and all responses) — FR-010

| Header | Baseline value |
|--------|----------------|
| `Strict-Transport-Security` | enabled (HSTS) |
| `X-Frame-Options` | `DENY` |
| `X-Content-Type-Options` | `nosniff` |
| `Referrer-Policy` | `no-referrer` |
| `Content-Security-Policy` | `default-src 'self'` (baseline; revisited with the SPA) |

### Performance

- p99 response time well under 1s (SC-004).

### Acceptance (maps to spec)

- Returns 200 + `{"status":"ok"}` once the stack is healthy (US1 AS-1, SC-001).
- Not reachable while startup is in progress or after a failed startup (US1 AS-2/3, reworded
  startup edge case).
- Every response carries the security headers above (US5 AS-3, SC-007).
