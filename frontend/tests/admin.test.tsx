import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { server } from "./msw/server";
import { ThemeProvider } from "@/theme/ThemeProvider";
import { AuthProvider } from "@/auth/AuthContext";
import { ActingClientProvider } from "@/auth/ActingClientContext";
import DashboardPage from "@/pages/DashboardPage";
import AdminConsole from "@/pages/AdminConsole";
import FailedQueue from "@/pages/FailedQueue";
import { AuditExportButton } from "@/components/admin/AuditExportButton";

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => vi.fn() };
});

const ADMIN_USER = {
  id: 2, email: "admin@example.com", role: "admin",
  user_type: "staff", client_id: null, is_active: true,
};

function TestWrapper({ children }: { children: React.ReactNode }) {
  localStorage.setItem("pantera_token", "token");
  localStorage.setItem("pantera_user", JSON.stringify(ADMIN_USER));
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

describe("DashboardPage", () => {
  it("shows empty-state when no usage data", async () => {
    server.use(
      http.get("http://localhost:8000/clients", () =>
        HttpResponse.json([{ id: 1, name: "Acme", status: "active" }]),
      ),
    );
    render(<TestWrapper><DashboardPage /></TestWrapper>);
    await waitFor(() =>
      expect(screen.getByText(/no llm usage recorded/i)).toBeInTheDocument(),
    );
  });

  it("shows pipeline metrics when ops data is available", async () => {
    server.use(
      http.get("http://localhost:8000/clients", () =>
        HttpResponse.json([{ id: 1, name: "Acme", status: "active" }]),
      ),
      http.get("http://localhost:8000/clients/1/metrics", () =>
        HttpResponse.json({
          client_id: 1,
          by_status: { drafted: 3, approved: 10 },
          queue: { pending: 3, expedited: 1, batch: 2 },
          sla: { overdue: 0, due_soon: 1, met_pct: 100 },
          redraft: { avg_revisions: 0.5, hit_cap: 0 },
          delivery: null,
          window: { from: null, to: null },
        }),
      ),
    );
    render(<TestWrapper><DashboardPage /></TestWrapper>);
    await waitFor(() => expect(screen.getByText("3")).toBeInTheDocument());
  });

  it("shows delivery card as pending (spec-13 forward dep)", async () => {
    server.use(
      http.get("http://localhost:8000/clients", () =>
        HttpResponse.json([{ id: 1, name: "Acme", status: "active" }]),
      ),
    );
    render(<TestWrapper><DashboardPage /></TestWrapper>);
    await waitFor(() =>
      expect(
        screen.getByText(/populates once the delivery layer/i),
      ).toBeInTheDocument(),
    );
  });
});

describe("FailedQueue", () => {
  const DLS = [
    {
      id: 1, job_name: "task_run_full_cycle", job_key: "fc:1", client_id: null,
      args_digest: "abc123", error_class: "OperationalError",
      error_summary: "Connection pool exhausted during cycle fan-out.",
      attempts: 4, first_failed_at: "2026-06-17T12:00:00Z",
      dead_lettered_at: "2026-06-17T12:05:00Z", resolved_at: null,
    },
    {
      id: 2, job_name: "task_consolidate_batch", job_key: "cb:2", client_id: 1,
      args_digest: "def456", error_class: "TimeoutError", error_summary: null,
      attempts: 3, first_failed_at: "2026-06-17T11:00:00Z",
      dead_lettered_at: "2026-06-17T11:05:00Z", resolved_at: null,
    },
  ];

  it("lists unresolved jobs with reason, system label, and null-summary fallback", async () => {
    server.use(
      http.get("http://localhost:8000/clients", () =>
        HttpResponse.json([{ id: 1, name: "Acme", status: "active" }]),
      ),
      http.get("http://localhost:8000/admin/dead-letters", () => HttpResponse.json(DLS)),
    );
    render(<TestWrapper><FailedQueue /></TestWrapper>);
    await waitFor(() =>
      expect(screen.getByText("OperationalError")).toBeInTheDocument(),
    );
    // null error_summary falls back to error_class → "TimeoutError" appears as
    // both the title and the reason line.
    expect(screen.getAllByText("TimeoutError").length).toBeGreaterThanOrEqual(2);
    // client_id null renders as "System".
    expect(screen.getByText("System")).toBeInTheDocument();
    // No retry/reprocess affordance — dead-lettered jobs cannot be replayed.
    expect(
      screen.queryByRole("button", { name: /retry|reprocess|re-?run/i }),
    ).toBeNull();
  });

  it("shows the empty state when there are no unresolved jobs", async () => {
    server.use(
      http.get("http://localhost:8000/clients", () => HttpResponse.json([])),
      http.get("http://localhost:8000/admin/dead-letters", () => HttpResponse.json([])),
    );
    render(<TestWrapper><FailedQueue /></TestWrapper>);
    await waitFor(() =>
      expect(screen.getByText(/no unresolved failed jobs/i)).toBeInTheDocument(),
    );
  });
});

describe("AuditExportButton", () => {
  it("renders as disabled with explanation", () => {
    render(
      <ThemeProvider>
        <MemoryRouter>
          <AuditExportButton />
        </MemoryRouter>
      </ThemeProvider>,
    );
    const btn = screen.getByRole("button", { name: /export audit log/i });
    expect(btn).toBeDisabled();
  });
});
