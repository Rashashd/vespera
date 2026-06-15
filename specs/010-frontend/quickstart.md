# Quickstart — Validate the Frontend SPA + New Endpoints (Spec 010)

Runnable validation that the feature works end-to-end. Implementation details live in `tasks.md`,
`contracts/`, and `data-model.md` — this is a run/verify guide.

> Host note (this Windows dev box): integration tests need the gitignored
> `docker-compose.override.yml` (ports 5433/6380) + localhost Vault repoint — see
> `memory/host-integration-test-vault-repoint.md`. Clean CI uses service names.

## Prerequisites

- Stack up: `docker compose up -d` (postgres, redis, vault, modelserver, app).
- Secrets in Vault (`scripts/write_secrets.py`). `langsmith_api_key` is **optional** — leave it empty
  to run with tracing disabled (the app still boots and the cost dashboard still works).
- Migration `0009` applied: `uv run alembic upgrade head` → confirm `llm_usage` exists.
- Node 20+ for the SPA.

## Backend: apply migration & sanity-check

```bash
uv run alembic upgrade head
uv run ruff check app && uv run black --check app   # both MUST pass
uv run pytest tests/unit tests/integration -k "passage or portal or usage or report_findings"
```

## Backend: exercise the new endpoints (against a seeded client + approved report)

```bash
# 1. login → token
TOKEN=$(curl -s -X POST localhost:8000/auth/jwt/login -d 'username=reviewer@x&password=…' | jq -r .access_token)

# 2. FR-006a all-reports (reviewer): every status
curl -s localhost:8000/clients/1/reports?status=all -H "Authorization: Bearer $TOKEN" | jq '.[].status'

# 3. FR-029 passage text — chunk_id comes from a claim's source_ref / corroboration passage_chunk_ids
curl -s localhost:8000/clients/1/passages/123 -H "Authorization: Bearer $TOKEN" | jq '{chunk_id,title,external_id}'
#    unknown/other-client chunk → 404 {"detail":"PASSAGE_UNAVAILABLE"}

# 4. FR-031 per-report findings
curl -s localhost:8000/clients/1/reports/5/findings -H "Authorization: Bearer $TOKEN" | jq '.[].state'

# 5. FR-030 client portal (login as a client-user) — approved+sent only, own client only
CTOKEN=$(curl -s -X POST localhost:8000/auth/jwt/login -d 'username=clientuser@x&password=…' | jq -r .access_token)
curl -s localhost:8000/clients/1/portal/reports -H "Authorization: Bearer $CTOKEN" | jq '.[].status'   # all approved/sent/delivered
curl -s -o /dev/null -w "%{http_code}\n" localhost:8000/clients/2/portal/reports -H "Authorization: Bearer $CTOKEN"  # 404 (not own client)

# 6. FR-021/034 cost dashboard (login as admin/manager)
curl -s localhost:8000/clients/1/usage -H "Authorization: Bearer $TOKEN" | jq '{total_cost_usd,call_count,by_call_site}'
```

**Expected:** (2) lists statuses beyond the review set; (3) returns exact passage text or 404
unavailable; (4) lists findings with drug/reaction/bucket/state; (5) client-user sees only own-client
approved+ reports and 404s on another client; (6) per-client totals reconcile with summed `llm_usage`.

## Cost capture round-trip (FR-032/033)

```bash
# Trigger a triage + an expedited draft for the client, then:
psql … -c "select call_site, model, input_tokens, output_tokens, cost_usd, finding_id from llm_usage where client_id=1 order by id desc limit 5;"
```
**Expected:** one row per external LLM call — `call_site` triage/agent, agent rows carry `finding_id`.
Cost/usage rows contain **no PII** and always work. LangSmith tracing is **OFF by default**: it
requires BOTH `tracing_enabled=true` AND a `langsmith_api_key`. When on, the triage call is traced
with inputs/outputs **redacted to non-PII metadata**; the drafting-agent path traces full content, so
tracing MUST stay disabled in production until the Presidio redaction sweep (spec 12) exists — enabling
it logs a warning to that effect.

## Frontend: run & validate

```bash
cd frontend
npm ci
npm run dev            # http://localhost:5173 ; VITE_API_BASE_URL → backend origin
npm run test           # Vitest component/integration (mocked API)
npm run test:e2e       # Playwright reviewer approve/reject happy path (needs the live stack)
npm run build          # production build (fresh-clone smoke)
```

## Full e2e against a live backend (verified 2026-06-15 on this Windows host)

The Playwright e2e (`frontend/e2e/`) hits the **real** stack (SPA at :5173 + API at :8000). Running it
end-to-end surfaced three integration bugs that mocked unit tests cannot (CORS, missing `GET
/auth/users/me`, login token-attach) — so this path is worth doing before shipping. Exact steps:

```bash
# 1. Infra only (avoids the slow API image build — run the API locally via uv instead).
docker compose up -d vault postgres redis
#    HOST GOTCHA: a host-installed Postgres may squat on :5432, shadowing the container. The
#    gitignored docker-compose.override.yml maps the containers to 5433/6380 — use those locally.
#    (If a stale pgdata volume has old creds: `docker compose down -v` then up again.)

# 2. Write Vault secrets pointing at the OVERRIDE ports. write_secrets.py demands an LLM key even
#    though login needs none — pass a dummy.
export VAULT_ADDR=http://localhost:8200 VAULT_TOKEN=root \
  DATABASE_URL="postgresql+asyncpg://pantera:pantera@localhost:5433/pantera" \
  REDIS_URL="redis://localhost:6380/0" ANTHROPIC_API_KEY="sk-dummy"
uv run python scripts/write_secrets.py

# 3. Migrate (alembic reads the URL from Vault).
uv run alembic upgrade head            # expect: 0009 (head)

# 4. Seed a reviewer (no seed script exists; insert directly, bypassing the password policy so the
#    e2e's default creds work). role='reviewer', user_type='staff', client_id=NULL.
uv run python - <<'PY'
import asyncio
from sqlalchemy import select
import app.audit.models, app.auth.models, app.clients.models, app.embedding.models, app.reports.models, app.triage.models, app.ingestion.models  # noqa: register tables
from app.auth.backend import password_helper
from app.auth.models import User
from app.core.config import get_settings
from app.core.startup import load_secrets_from_vault
from app.db.base import create_engine, create_session_factory
async def main():
    s = get_settings(); await load_secrets_from_vault(s)
    e = create_engine(s.database_url); f = create_session_factory(e)
    async with f() as session:
        if await session.scalar(select(User).where(User.email=='reviewer@example.com')):
            print('exists'); await e.dispose(); return
        session.add(User(email='reviewer@example.com', hashed_password=password_helper.hash('password'),
                         role='reviewer', user_type='staff', client_id=None,
                         is_active=True, is_superuser=False, is_verified=True))
        await session.commit(); print('reviewer created')
    await e.dispose()
asyncio.run(main())
PY

# 5. Run the API locally (uses Vault secrets → 5433/6380). CORS for :5173 is on by default
#    (Settings.cors_allow_origins).
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 &   # wait for GET /health = 200

# 6. Serve the built SPA and run the e2e (default creds reviewer@example.com / password).
cd frontend && npm run build && (npx vite preview --port 5173 &)
PLAYWRIGHT_BASE_URL=http://localhost:5173 npx playwright install chromium
PLAYWRIGHT_BASE_URL=http://localhost:5173 npx playwright test     # expect: 2 passed
```
Teardown: `npx kill-port 8000 5173 && docker compose down -v`.

### Manual smoke per role
- **Reviewer** → lands on `/queue`: drafts-only, expedited-first with SLA countdown; open a report →
  all structured claims + body + **all N** citations; click a citation → exact passage drawer; take
  each action (approve / edit-approve / reject-with-comment / discard) → report leaves the queue.
  Open `/reports` → all statuses with a delivery-status label ("Approved (pending delivery)").
- **Manager/Admin** → `/admin`: create a client, add a watchlist + custom severity keyword, trigger a
  manual per-watchlist ingest (202 "queued"); `/admin/usage` shows per-client cost (or an empty state).
- **Client-user** → `/portal`: one page per watchlist listing **approved+sent** reports only,
  read-only (no decision/config controls); cannot reach another client or any in-workflow report.
- **Any role** → reload keeps the session; expired/invalid token returns to `/login` with a clear,
  non-enumerating error.

## Acceptance gate mapping

| Check | Spec |
|---|---|
| All N citations shown; each passage openable | SC-002 / FR-009 / FR-010 / FR-029 |
| Only reviewers can decide; no send without a reviewer decision | SC-003 / FR-016 |
| Each role reaches only permitted surfaces (nav + direct URL) | SC-004 / FR-004 |
| Two reviewers → exactly one decision, other gets conflict | SC-005 / FR-017 |
| Client-user sees only own approved+sent, grouped by watchlist | SC-008 / FR-023 / FR-030 |
| Fresh-clone builds + serves the SPA | SC-009 |
| Component tests across surfaces + one e2e | SC-010 |
| Every LLM call → a client-attributed usage row; dashboard reconciles | SC-011 / FR-032/033/034 |
| Both linters pass on backend changes | constitution |
