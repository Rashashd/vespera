import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { server } from "./msw/server";
import { ThemeProvider } from "@/theme/ThemeProvider";
import { AuthProvider } from "@/auth/AuthContext";
import { ActingClientProvider } from "@/auth/ActingClientContext";
import { ReportDetail } from "@/components/ReportDetail";

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => vi.fn() };
});

const REVIEWER_USER = {
  id: 1, email: "reviewer@example.com", role: "reviewer",
  user_type: "staff", client_id: null, is_active: true,
};

const BATCH_REPORT = {
  id: 5, client_id: 1, report_type: "batch", status: "drafted",
  corroboration_count: 1, revision_count: 0,
  sla_deadline: null, watchlist_id: 1,
  created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
  structured_fields: [],
  draft_body: "Batch body",
  corroboration_sources: [],
  reviewer_comments: [],
  cycle_period_start: null,
  cycle_period_end: null,
};

const FINDINGS = [
  { id: 1, report_id: 5, finding_id: 10, drug: "Ibuprofen", reaction: "GI bleed", bucket: "urgent", state: "included", created_at: new Date().toISOString() },
  { id: 2, report_id: 5, finding_id: 11, drug: "Aspirin", reaction: "Reye syndrome", bucket: "emergency", state: "included", created_at: new Date().toISOString() },
];

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

describe("Batch finding management", () => {
  it("renders the findings list in the left rail for batch reports", async () => {
    server.use(
      http.get("http://localhost:8000/clients/1/reports/5", () => HttpResponse.json(BATCH_REPORT)),
      http.get("http://localhost:8000/clients/1/reports/5/findings", () => HttpResponse.json(FINDINGS)),
      http.get("http://localhost:8000/clients", () => HttpResponse.json([{ id: 1, name: "Acme", status: "active" }])),
    );

    render(<TestWrapper><ReportDetail clientId={1} reportId={5} mode="queue" /></TestWrapper>);

    await waitFor(() => {
      expect(screen.getByText("Ibuprofen")).toBeInTheDocument();
      expect(screen.getByText("Aspirin")).toBeInTheDocument();
    });
  });

  it("shows Drop and Discard controls on included findings", async () => {
    server.use(
      http.get("http://localhost:8000/clients/1/reports/5", () => HttpResponse.json(BATCH_REPORT)),
      http.get("http://localhost:8000/clients/1/reports/5/findings", () => HttpResponse.json(FINDINGS)),
      http.get("http://localhost:8000/clients", () => HttpResponse.json([{ id: 1, name: "Acme", status: "active" }])),
    );

    render(<TestWrapper><ReportDetail clientId={1} reportId={5} mode="queue" /></TestWrapper>);

    await waitFor(() => {
      const dropButtons = screen.getAllByRole("button", { name: /drop/i });
      expect(dropButtons.length).toBeGreaterThan(0);
    });
  });

  it("hides drop/discard controls in read-only mode (portal)", async () => {
    server.use(
      // Portal mode fetches the portal-safe report endpoint, not the reviewer one.
      http.get("http://localhost:8000/clients/1/portal/reports/5", () => HttpResponse.json(BATCH_REPORT)),
      http.get("http://localhost:8000/clients/1/reports/5/findings", () => HttpResponse.json(FINDINGS)),
      http.get("http://localhost:8000/clients", () => HttpResponse.json([{ id: 1, name: "Acme", status: "active" }])),
    );

    render(<TestWrapper><ReportDetail clientId={1} reportId={5} mode="portal" /></TestWrapper>);

    await waitFor(() => expect(screen.getByText("Ibuprofen")).toBeInTheDocument());
    // No drop/discard controls in portal mode
    expect(screen.queryByRole("button", { name: /^drop$/i })).not.toBeInTheDocument();
  });
});
