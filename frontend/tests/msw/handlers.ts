import { http, HttpResponse } from "msw";

const BASE = "http://localhost:8000";

// Default handlers — individual tests override these via server.use(...)
export const handlers = [
  // Auth
  http.post(`${BASE}/auth/jwt/login`, () =>
    HttpResponse.json({ access_token: "test-token", token_type: "bearer" }),
  ),
  http.get(`${BASE}/auth/users/me`, () =>
    HttpResponse.json({
      id: 1,
      email: "reviewer@example.com",
      role: "reviewer",
      user_type: "staff",
      client_id: null,
      is_active: true,
    }),
  ),

  // Reports queue
  http.get(`${BASE}/clients/:clientId/reports`, ({ request }) => {
    const url = new URL(request.url);
    const status = url.searchParams.get("status");
    if (status === "all") {
      return HttpResponse.json([]);
    }
    return HttpResponse.json([]);
  }),

  // Report detail
  http.get(`${BASE}/clients/:clientId/reports/:reportId`, () =>
    HttpResponse.json(null, { status: 404 }),
  ),

  // Passage
  http.get(`${BASE}/clients/:clientId/passages/:chunkId`, () =>
    HttpResponse.json(null, { status: 404, statusText: "PASSAGE_UNAVAILABLE" }),
  ),

  // Report findings
  http.get(`${BASE}/clients/:clientId/reports/:reportId/findings`, () =>
    HttpResponse.json([]),
  ),

  // Portal
  http.get(`${BASE}/clients/:clientId/portal/reports`, () =>
    HttpResponse.json([]),
  ),

  // Clients list (for acting-client switcher)
  http.get(`${BASE}/clients`, () => HttpResponse.json([])),

  // Watchlists
  http.get(`${BASE}/clients/:clientId/watchlists`, () =>
    HttpResponse.json([]),
  ),

  // Usage dashboard
  http.get(`${BASE}/clients/:clientId/usage`, () =>
    HttpResponse.json({
      client_id: 1,
      total_cost_usd: "0.000000",
      total_input_tokens: 0,
      total_output_tokens: 0,
      call_count: 0,
      by_call_site: {},
      window: { from: null, to: null },
    }),
  ),

  // Ops metrics
  http.get(`${BASE}/clients/:clientId/metrics`, () =>
    HttpResponse.json({
      client_id: 1,
      by_status: {},
      queue: { pending: 0, expedited: 0, batch: 0 },
      sla: { overdue: 0, due_soon: 0, met_pct: 100 },
      redraft: { avg_revisions: 0, hit_cap: 0 },
      delivery: null,
      window: { from: null, to: null },
    }),
  ),
];
