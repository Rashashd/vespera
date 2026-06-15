import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { server } from "./msw/server";
import { ThemeProvider } from "@/theme/ThemeProvider";
import { AuthProvider } from "@/auth/AuthContext";
import { ActingClientProvider } from "@/auth/ActingClientContext";
import ReviewerQueue from "@/pages/ReviewerQueue";
import { ReportDetail } from "@/components/ReportDetail";

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => vi.fn() };
});

const REVIEWER_USER = {
  id: 1, email: "reviewer@example.com", role: "reviewer",
  user_type: "staff", client_id: null, is_active: true,
};

const EXPEDITED_REPORT = {
  id: 1, client_id: 1, report_type: "expedited", status: "drafted",
  corroboration_count: 2, revision_count: 0,
  sla_deadline: new Date(Date.now() + 3_600_000).toISOString(),
  watchlist_id: null, created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

const OVERDUE_REPORT = {
  ...EXPEDITED_REPORT,
  id: 2,
  sla_deadline: new Date(Date.now() - 3_600_000).toISOString(),
};

function TestWrapper({ children }: { children: React.ReactNode }) {
  localStorage.setItem("pantera_token", "token");
  localStorage.setItem("pantera_user", JSON.stringify(REVIEWER_USER));
  localStorage.setItem("pantera_acting_client", "1");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <ThemeProvider>
      <QueryClientProvider client={qc}>
        <AuthProvider>
          <ActingClientProvider>
            <MemoryRouter>
              {children}
            </MemoryRouter>
          </ActingClientProvider>
        </AuthProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}

describe("ReviewerQueue", () => {
  it("shows expedited reports before batch", async () => {
    server.use(
      http.get("http://localhost:8000/clients/1/reports", () =>
        HttpResponse.json([
          { ...EXPEDITED_REPORT, id: 10, report_type: "batch" },
          { ...EXPEDITED_REPORT, id: 11, report_type: "expedited" },
        ]),
      ),
      http.get("http://localhost:8000/clients", () => HttpResponse.json([{ id: 1, name: "Acme", status: "active" }])),
    );
    render(<TestWrapper><ReviewerQueue /></TestWrapper>);
    await waitFor(() => expect(screen.getByText("#11")).toBeInTheDocument());
    // Expedited (#11) should appear before batch (#10)
    const items = screen.getAllByRole("button").filter((b) =>
      b.getAttribute("aria-label")?.includes("Report"),
    );
    expect(items[0]).toHaveAttribute("aria-label", expect.stringContaining("Report 11"));
  });

  it("shows overdue banner when there are overdue expedited reports", async () => {
    server.use(
      http.get("http://localhost:8000/clients/1/reports", () =>
        HttpResponse.json([OVERDUE_REPORT]),
      ),
      http.get("http://localhost:8000/clients", () => HttpResponse.json([{ id: 1, name: "Acme", status: "active" }])),
    );
    render(<TestWrapper><ReviewerQueue /></TestWrapper>);
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(/overdue/i),
    );
  });

  it("shows empty state when queue is empty", async () => {
    server.use(
      http.get("http://localhost:8000/clients/1/reports", () => HttpResponse.json([])),
      http.get("http://localhost:8000/clients", () => HttpResponse.json([{ id: 1, name: "Acme", status: "active" }])),
    );
    render(<TestWrapper><ReviewerQueue /></TestWrapper>);
    await waitFor(() =>
      expect(screen.getByText(/queue is empty/i)).toBeInTheDocument(),
    );
  });
});

describe("ReportDetail", () => {
  const FULL_REPORT = {
    ...EXPEDITED_REPORT,
    structured_fields: [
      { text: "Drug: Atorvastatin", provenance: "drafted_grounded", source_ref: "42" },
      { text: "Reaction: Rhabdomyolysis", provenance: "drafted_grounded", source_ref: null },
    ],
    draft_body: "This is the narrative body.",
    corroboration_sources: [
      {
        document_id: 1,
        title: "Case report of rhabdomyolysis",
        external_id: "PMID:12345",
        source_reliability: "peer_reviewed",
        passage_chunk_ids: [42],
      },
    ],
    reviewer_comments: [],
    cycle_period_start: null,
    cycle_period_end: null,
  };

  it("renders all N citations and passage-unavailable fallback", async () => {
    server.use(
      http.get("http://localhost:8000/clients/1/reports/1", () => HttpResponse.json(FULL_REPORT)),
      http.get("http://localhost:8000/clients/1/reports/1/findings", () => HttpResponse.json([])),
      http.get("http://localhost:8000/clients/1/passages/42", () =>
        HttpResponse.json({ detail: "PASSAGE_UNAVAILABLE" }, { status: 404 }),
      ),
      http.get("http://localhost:8000/clients", () => HttpResponse.json([{ id: 1, name: "Acme", status: "active" }])),
    );

    render(
      <TestWrapper>
        <ReportDetail clientId={1} reportId={1} mode="queue" />
      </TestWrapper>,
    );

    await waitFor(() =>
      expect(screen.getByText("Case report of rhabdomyolysis")).toBeInTheDocument(),
    );

    // Click the citation to open the drawer
    fireEvent.click(screen.getByText("Case report of rhabdomyolysis"));

    await waitFor(() =>
      expect(screen.getByText(/passage unavailable/i)).toBeInTheDocument(),
    );
  });

  it("renders three visually distinct provenance classes", async () => {
    server.use(
      http.get("http://localhost:8000/clients/1/reports/2", () =>
        HttpResponse.json({
          ...FULL_REPORT,
          id: 2,
          structured_fields: [
            { text: "Drug: X", provenance: "drafted_grounded", source_ref: "1" },
            { text: "Reaction: Y", provenance: "reviewer_attested", source_ref: null },
            { text: "Summary", provenance: "aggregated", source_ref: null },
          ],
        }),
      ),
      http.get("http://localhost:8000/clients/1/reports/2/findings", () => HttpResponse.json([])),
      http.get("http://localhost:8000/clients", () => HttpResponse.json([{ id: 1, name: "Acme", status: "active" }])),
    );

    render(<TestWrapper><ReportDetail clientId={1} reportId={2} mode="queue" /></TestWrapper>);

    // Scope to the claims section so /grounded/ doesn't also match the citation button.
    await waitFor(() =>
      expect(screen.getByRole("region", { name: /structured claims/i })).toBeInTheDocument(),
    );
    const claims = screen.getByRole("region", { name: /structured claims/i });
    expect(within(claims).getByTitle(/^grounded/i)).toBeInTheDocument();
    expect(within(claims).getByTitle(/reviewer-added/i)).toBeInTheDocument();
    expect(within(claims).getByTitle(/aggregated/i)).toBeInTheDocument();
  });

  it("shows keyboard-operable action buttons", async () => {
    server.use(
      http.get("http://localhost:8000/clients/1/reports/3", () =>
        HttpResponse.json({ ...FULL_REPORT, id: 3 }),
      ),
      http.get("http://localhost:8000/clients/1/reports/3/findings", () => HttpResponse.json([])),
      http.get("http://localhost:8000/clients", () => HttpResponse.json([{ id: 1, name: "Acme", status: "active" }])),
    );

    render(<TestWrapper><ReportDetail clientId={1} reportId={3} mode="queue" /></TestWrapper>);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /approve/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /reject/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /discard/i })).toBeInTheDocument();
    });

    // All action buttons must be focusable
    const approve = screen.getByRole("button", { name: /approve/i });
    approve.focus();
    expect(document.activeElement).toBe(approve);
  });
});
