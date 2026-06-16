# Contract: Redaction (Presidio, in-process)

`app/redaction/redactor.py` — `redact(text: str) -> RedactionResult`. Process-singleton analyzer/anonymizer (`@lru_cache`, mirror `app/triage/ner.py:_get_nlp`). Offload the CPU-bound analyze with `asyncio.to_thread` if called from async paths.

## Function contract

```python
def redact(text: str) -> RedactionResult: ...
# RedactionResult.text  -> redacted string (placeholders like "<PERSON>", "<SECRET>")
# RedactionResult.entities -> list of (type, count) — category + count ONLY, never the original value
```

- Idempotent-safe: redacting already-redacted text is a no-op on placeholders.
- Empty/whitespace input → returns input unchanged, empty entities.
- MUST NOT log the input text or any matched value (FR-014).

## PII categories (Presidio recognizers)

Default Presidio entities to enable: `PERSON`, `DATE_TIME` (DOB), `PHONE_NUMBER`, `EMAIL_ADDRESS`, `LOCATION`/address, `US_SSN`/national-id-style, plus a custom `MEDICAL_RECORD_NUMBER`/case-number recognizer (regex). spaCy model for NER = `en_core_web_sm` (pin; small, torch-free) — NOT scispaCy `en_ner_bc5cdr_md` (that is a biomedical chemical/disease model, not PII).

## Secret patterns (custom recognizer, `app/redaction/recognizers.py`)

Regexes for common key/token shapes: `sk-...` (OpenAI), `sk-ant-...` (Anthropic), generic high-entropy `[A-Za-z0-9_\-]{32,}` bearer/api-key contexts, AWS `AKIA...`, JWT `eyJ...\.`. Emit category `SECRET`. Tune to avoid redacting ordinary identifiers (anchor on key-like prefixes/length + context word "key/token/secret").

## Signal preservation (FR-011)

Redaction MUST NOT remove drug names, reaction/AE terms, or severity-relevant clinical content. The redaction golden set includes legitimate clinical control cases; the CI gate fails if a control case is over-redacted (a drug/AE term replaced) — `guardrail`-style `false` metric, see `eval_thresholds.yaml security.redaction_*`.

## Egress integration points

| Point | Where | Note |
|---|---|---|
| External LLM (triage) | `app/triage/llm.py` `resolve_yes_no`/`assess_valence` — redact `text` before `_call_llm` | covers raw document text |
| External LLM (agent) | `app/agent/graph.py` `agent_node` — redact message content before `chat_model.ainvoke` | covers retrieved RAG context in ToolMessages; citations are chunk_id refs (unaffected) |
| Logs | `app/observability/logging.py` | structlog processor redacts string event values before render |
| Traces | `app/observability/tracing.py` | extend agent-path trace redaction (FR-023); triage already drops to safe keys |
| Derived stored summaries | any persisted operational summary | NOT the report body/findings (full-fidelity) |

## Ordering (FR-012)

`redact()` runs **before** the guardrails `guard(input)` call and **before** the external LLM call, on every guarded path.
