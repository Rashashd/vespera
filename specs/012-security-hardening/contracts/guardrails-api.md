# Contract: Guardrails Sidecar HTTP API

Lean, torch-free FastAPI service in top-level `guardrails/` (mirrors `modelserver/`). Called by `app/guardrails/client.py` over HTTP with a service credential. No external LLM, no torch.

## Auth

Header `X-Service-Token: <guardrails_token>` on every request (same pattern as modelserver's `X-Service-Token`). Missing/wrong → `401`. Token comes from Vault; the sidecar reads it via the same secret-loading approach as modelserver (env/Vault), the app sends `settings.guardrails_token`.

## `POST /guard`

Evaluate one payload against the platform rails.

**Request**
```json
{
  "text": "string — the prompt OR the model output to check",
  "direction": "input" | "output",
  "client_id": 123,
  "call_site": "triage" | "agent" | "intake"
}
```

**Response 200**
```json
{
  "action": "allow" | "block",
  "rail": "injection" | "jailbreak" | "topic_scope" | "cross_client" | null,
  "reason": "non-PII reason code or null",
  "checked": ["injection", "jailbreak", "topic_scope", "cross_client"]
}
```

- `action="block"` ⇒ `rail` + `reason` populated; the FIRST blocking rail short-circuits.
- `action="allow"` ⇒ `rail=null`, all applicable rails passed.
- Rails applied per direction: input → all four; output → injection-echo + topic_scope + cross_client (jailbreak is input-only).
- Response MUST NOT echo `text` or any PII.

**Errors**: `401` (bad token), `422` (malformed body). The sidecar MUST NOT 5xx on rail evaluation; a rule engine error returns `action="block"` with `reason="rail_engine_error"` (fail-safe inside the sidecar).

## `GET /health`

`200 {"status":"ok"}` — no auth (matches modelserver health probe in docker-compose).

## Client-side behavior (`app/guardrails/client.py`)

- httpx.AsyncClient + tenacity `stop_after_attempt(3)`, retry on timeout/5xx/network only, never on 4xx (mirror `app/infra/modelserver_client.py` and the triage `_should_retry`).
- On exhausted retries / unreachable sidecar → raise a typed `GuardrailsUnavailable`; callers translate to the fail-safe per call site (triage escalate, agent escalate, intake quarantine) and raise `GuardrailUnavailable` domain event.
- The app calls `guard()` twice per LLM call: once on the redacted input, once on the model output.

## Determinism

Rails are deterministic (regex/keyword/optional fixed ONNX classifier) so the CI red-team gate is stable. No randomness, no network calls out of the sidecar.
