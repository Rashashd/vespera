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
      expect(screen.getByText(/delivery metrics are pending/i)).toBeInTheDocument(),
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
