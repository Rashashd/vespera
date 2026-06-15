# AI Implementation Pitfalls — a reusable pre-ship checklist

Generalized from real bugs found while QA-ing an AI-implemented full-stack feature (React SPA +
FastAPI backend). Every item below is a mistake that **shipped "done"** but broke on first real use.
Project-agnostic — copy this into any project and run the **Pre-flight** before trusting "it's done."

> The meta-lesson: **a checked-off task list and a green *mocked* test suite prove almost nothing.**
> The app was committed unbuildable, with a test suite that had never been executed, and three
> integration bugs that made it 100% non-functional in a browser — all behind "all tasks complete."

---

## ✅ Pre-flight checklist (run before claiming done / before pushing)

```
# Frontend
[ ] deps actually resolve:        npm install          (no 404s)
[ ] lockfile committed:           git status           (package-lock.json present)
[ ] it builds:                    npm run build
[ ] it type-checks:               npm run typecheck / tsc -b
[ ] tests actually run + pass:    npm run test
[ ] linter actually runs:         npm run lint
# Backend
[ ] both formatters:              ruff check . && black --check .
[ ] unit tests:                   pytest tests/unit
[ ] integration tests on a REAL db: pytest tests/integration   (not just collected)
# Integration (the part mocks can't prove)
[ ] one real e2e against a LIVE backend in a REAL browser passes
[ ] every endpoint the client calls exists with the right METHOD and response shape
[ ] cross-origin works (CORS) — test in a browser, not curl
```

If you didn't *run* it, it isn't done.

---

## A. "Done" discipline

- **A1 — Code committed unbuildable / tests never run.** The whole frontend couldn't `npm install`,
  yet was committed as complete with a "passing" suite. → Always run install→build→typecheck→test→lint
  before committing. CI must run all of these (it would have caught it — but only if it runs).
- **A2 — Mocked tests passed while the app was broken end-to-end.** 26/26 component tests (mocked API)
  were green while the SPA was non-functional against a real backend. → Mocks hide integration seams.
  Always include at least **one real e2e against a live backend**.

## B. Dependencies & build scaffolding

- **B1 — Hallucinated dependency.** A package that doesn't exist (`@radix-ui/react-badge`) was added,
  404-ing every install. → Verify each dependency exists (`npm view <pkg> version`) before adding;
  never trust an LLM's package names. One bogus dep blocks the entire project.
- **B2 — Missing framework scaffolding file.** No `src/vite-env.d.ts` → `import.meta.env` untyped,
  build fails. → Don't omit the framework's generated boilerplate.
- **B3 — Lockfile not committed.** `npm ci` (used by CI and Docker) **requires** a lockfile; without it
  the container build and CI fail. → Always commit `package-lock.json` / `pnpm-lock.yaml`.

## C. Test-suite hygiene

- **C1 — jsdom missing browser APIs.** `ResizeObserver`/`matchMedia`/`scrollIntoView` are absent in
  jsdom; component libs (cmdk, Radix) crash. → Polyfill them in the test setup file.
- **C2 — Brittle / ambiguous assertions.** Asserting an exact string the component doesn't emit
  (`"#11"` vs aria-label `"Report 11"`); a loose regex matching the wrong node (`/grounded/i` also
  matched "not **grounded**"). → Scope queries (`within(section)`), anchor regexes (`/^grounded/`),
  assert on stable roles/attributes.
- **C3 — Fixtures referenced but never defined.** Integration tests used `authed_*_client` fixtures
  that existed nowhere → every test errored at setup. → Running the suite once catches this instantly;
  undefined fixtures fail loudly.

## D. Frontend ↔ Backend integration (mocks can't catch these)

- **D1 — No CORS.** A separate-origin SPA → API call returns 200 server-side, but the browser blocks
  the JS from reading it without `Access-Control-Allow-Origin`. The app looked broken with no error.
  → A separate-origin SPA **requires** CORS middleware. Verify in a browser; `curl` ignores CORS.
- **D2 — Client calls a non-existent / wrong-method endpoint.** The SPA needed `GET /auth/users/me`;
  only `PATCH` existed → 405, then 401. → Verify every endpoint the client calls actually exists with
  the right method **and** response shape. Keep a client↔server contract.
- **D3 — Auth token race.** Login fetched the "current user" endpoint *before* persisting the token →
  unauthenticated 401. → In token flows, attach the just-issued token explicitly to the immediate
  follow-up request; never rely on async storage having landed.

## E. Security / authorization

- **E1 — Broken object-level authorization.** An endpoint checked only the tenant, not the resource's
  *visibility status*, so a low-privilege user could read in-workflow/unpublished data for their tenant.
  → Every read must enforce the **same visibility rule as its sibling endpoints**, not just tenancy.
- **E2 — Over-broad reads (enumeration).** An endpoint let a user fetch any resource id within their
  tenant (the whole corpus), not just ones they're entitled to see. → Scope reads to what the user can
  actually see (e.g., only items referenced by records they're allowed to view).
- **E3 — Assumed compensating control not implemented.** Storing the JWT in `localStorage` was
  "justified by CSP" — but the SPA was served with **no CSP headers at all**. → If a security decision
  depends on a control (CSP, security headers), actually implement and verify that control ships.

## F. Observability & PII

- **F1 — Dead instrumentation.** A tracing decorator was defined but applied nowhere, so the "trace
  every LLM call" requirement was silently unmet. → Wire it or delete it; grep that obs/safety hooks
  are actually used.
- **F2 — PII to third parties before redaction.** Enabling external tracing would have shipped
  unredacted clinical/user text to a SaaS. → Gate external telemetry behind an explicit **off-by-default**
  switch; **redact inputs/outputs** to non-PII metadata; never send PII/secrets to third parties.

## G. Tooling & CI

- **G1 — package.json script that can't run.** `npm run lint` referenced ESLint that wasn't installed
  and had no config. → Every script in the manifest must actually execute; CI should run lint too.
- **G2 — Unregistered test markers.** `@pytest.mark.integration` not registered → warnings/footguns.
  → Register custom markers in config.
- **G3 — Linter-clean but formatter-dirty.** Code passed `ruff` but failed `black`. → Run **both** the
  linter and the formatter; they enforce different things.

## H. Local environment & ops (bring-up friction)

- **H1 — Host service squatting on a port.** A host-installed Postgres on `:5432` shadowed the Docker
  container; the app authed against the wrong DB. → Beware host port collisions; map containers to
  distinct ports; verify *which process answers* (`netstat`/`docker port`).
- **H2 — Stale data volume with old credentials.** Postgres only applies `POSTGRES_PASSWORD` on first
  init; a leftover volume keeps old creds. → `docker compose down -v` to reset when auth mysteriously
  fails on a "fresh" DB.
- **H3 — Bootstrap tool gated on an unrelated requirement.** The secret-writer demanded an LLM API key
  even for a login-only flow. → Know your bootstrap prerequisites and document the local bring-up
  (a runnable quickstart) so the next person isn't blocked.

---

## The five habits that would have prevented ~all of the above
1. **Run it, don't assume it.** Install, build, type-check, test, lint — actually execute them.
2. **One real e2e beats a hundred mocks** for catching CORS, missing endpoints, and auth races.
3. **Verify every external name exists** — dependencies, endpoints, fixtures, env vars.
4. **Security controls must ship, not just be cited** — CSP, authz status-gates, PII redaction.
5. **Make CI run the same checks** so "done" can't be faked.
