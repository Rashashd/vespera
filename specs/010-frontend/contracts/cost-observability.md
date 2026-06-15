# Contract — Observability & Cost Attribution (Spec 010, FR-032–035)

Two external LLM call sites are traced and metered. Everything is **best-effort**: a tracing or
usage-write failure MUST NOT fail or block the underlying pipeline operation (FR-033).

---

## Call sites (the only two — ONNX is excluded)

| Site | File / function | Has client_id? | Has finding_id? | Token source |
|---|---|---|---|---|
| Agent drafting | `app/agent/graph.py:agent_node` | yes (`client.id`) | yes (`finding.id`) | `response.usage_metadata` → `input_tokens`, `output_tokens` |
| Triage valence/resolve | `app/triage/llm.py` (`_call_llm` / `resolve_yes_no` / `assess_valence`) | yes (`client_id`) | no (pass `None`) | provider JSON `usage`: Anthropic `input_tokens`/`output_tokens`; OpenAI `prompt_tokens`/`completion_tokens` |

ONNX classifier + embedder (via modelserver) make no external call → **not** traced or metered.

## `record_usage()` — `app/observability/usage.py`

```
async def record_usage(
    *, session, client_id: int, finding_id: int | None,
    call_site: str, model: str, input_tokens: int, output_tokens: int, settings,
) -> None
```
- Computes `cost_usd` via `pricing.compute_cost(model, input_tokens, output_tokens, settings)`
  returning a `Decimal`.
- Inserts one `llm_usage` row (see data-model.md).
- Wraps the write in `try/except Exception` → `structlog.warning("usage.record_failed", ...)` and
  returns; **never re-raises**. Binds `client_id`/`finding_id` on the log line (never PII).
- Reuses the caller's `session`. Do not open a new engine/connection.

## `pricing.py` — token → Decimal cost

```
compute_cost(model, in_tok, out_tok, settings) -> Decimal:
    price_in  = settings.<per-1k-input price for model>   # USD per 1K input tokens
    price_out = settings.<per-1k-output price for model>  # USD per 1K output tokens
    return (Decimal(in_tok)/1000 * Decimal(str(price_in))
          + Decimal(out_tok)/1000 * Decimal(str(price_out)))
```
Unknown model ⇒ price 0 + a logged warning (don't crash). Use `Decimal` end-to-end so SC-011 sums
reconcile exactly with the dashboard total.

## `tracing.py` — LangSmith, degrade gracefully

```
def configure_tracing(settings) -> None:
    if not settings.langsmith_api_key:
        return                      # disabled; app boots normally
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"]    = settings.langsmith_api_key
    os.environ["LANGCHAIN_PROJECT"]    = settings.langsmith_project
```
- Call once at startup, **after** `load_secrets_from_vault(...)`, **before** any agent run.
- Agent path traces automatically (LangChain chat models).
- Triage path: decorate the call with `langsmith.traceable` imported lazily inside a try/except so a
  missing/disabled langsmith never breaks triage:
  ```
  try:
      from langsmith import traceable
  except Exception:
      def traceable(*a, **k):  # no-op fallback
          return (lambda f: f)
  ```
- Tag runs with `client_id`/`finding_id` metadata. **No prompt/response text in tags** (FR-035).

## Config (`app/core/config.py`) — see implementation-notes §7

- `langsmith_api_key: str = ""` — secret, optional, from Vault, **NOT** in `_REQUIRED_SECRETS`
  (so no ci.yml inline-secret change; CI/fresh-clone stay green without it).
- `langsmith_project: str = "pantera"`.
- per-1K-token input/output USD prices keyed by pinned model id (unit + currency in the field
  name/comment).

## Dashboard read — see backend-endpoints.md (FR-021/034)

`GET /clients/{id}/usage` aggregates `llm_usage` **only** (never LangSmith at view-time). SC-011:
the per-client total equals the sum of that client's `llm_usage.cost_usd` rows.

## Acceptance hooks

- A triage call and an agent run each write exactly one `llm_usage` row tagged with the right
  `client_id` (+ `finding_id` for agent).
- With `langsmith_api_key=""`, the full pipeline runs and the dashboard still works (tracing off).
- Forcing a `record_usage` DB error does not fail the triage/agent operation (logged + swallowed).
