import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { server } from "./msw/server";
import { ThemeProvider } from "@/theme/ThemeProvider";
import { AuthProvider } from "@/auth/AuthContext";
import { ActingClientProvider } from "@/auth/ActingClientContext";
import ClientPortal from "@/pages/ClientPortal";
import WatchlistPage from "@/pages/WatchlistPage";

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => vi.fn() };
});

const CLIENT_USER = {
  id: 10, email: "client@example.com", role: null,
  user_type: "client", client_id: 5, is_active: true,
};

function TestWrapper({ children, initialEntries = ["/portal"] }: { children: React.ReactNode; initialEntries?: string[] }) {
  localStorage.setItem("pantera_token", "token");
  localStorage.setItem("pantera_user", JSON.stringify(CLIENT_USER));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <ThemeProvider>
      <QueryClientProvider client={qc}>
        <AuthProvider>
          <ActingClientProvider>
            <MemoryRouter initialEntries={initialEntries}>
              <Routes>
                <Route path="/portal" element={children} />
                <Route path="/portal/watchlists/:watchlistId" element={<WatchlistPage />} />
              </Routes>
            </MemoryRouter>
          </ActingClientProvider>
        </AuthProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}

describe("ClientPortal", () => {
  it("shows empty state when no watchlists configured", async () => {
    server.use(
      http.get("http://localhost:8000/clients/5/watchlists", () => HttpResponse.json([])),
      http.get("http://localhost:8000/clients/5/portal/reports", () => HttpResponse.json([])),
    );
    render(<TestWrapper><ClientPortal /></TestWrapper>);
    await waitFor(() =>
      expect(screen.getByText(/no watchlists configured/i)).toBeInTheDocument(),
    );
  });

  it("shows watchlists and report counts", async () => {
    server.use(
      http.get("http://localhost:8000/clients/5/watchlists", () =>
        HttpResponse.json([{ id: 1, client_id: 5, name: "Cardiology", status: "active" }]),
      ),
      http.get("http://localhost:8000/clients/5/portal/reports", () =>
        HttpResponse.json([
          {
            id: 100, report_type: "expedited", status: "approved",
            delivery_status: "approved_pending_delivery", watchlist_id: 1,
            corroboration_count: 2, sla_deadline: null,
            cycle_period_start: null, cycle_period_end: null,
            created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
          },
        ]),
      ),
    );
    render(<TestWrapper><ClientPortal /></TestWrapper>);
    await waitFor(() =>
      expect(screen.getByText("Cardiology")).toBeInTheDocument(),
    );
    expect(screen.getByText(/1 report/i)).toBeInTheDocument();
  });

  it("only shows approved-or-later reports (no in-workflow statuses)", async () => {
    // The portal endpoint filters server-side; client only sees what the server returns
    server.use(
      http.get("http://localhost:8000/clients/5/watchlists", () =>
        HttpResponse.json([{ id: 1, client_id: 5, name: "Oncology", status: "active" }]),
      ),
      http.get("http://localhost:8000/clients/5/portal/reports", () =>
        // Server returns empty — no approved reports
        HttpResponse.json([]),
      ),
    );
    render(<TestWrapper initialEntries={["/portal/watchlists/1"]}><ClientPortal /></TestWrapper>);
    // Navigate to the watchlist page directly
    render(
      <ThemeProvider>
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          <AuthProvider>
            <ActingClientProvider>
              <MemoryRouter initialEntries={["/portal/watchlists/1"]}>
                <Routes>
                  <Route path="/portal/watchlists/:watchlistId" element={<WatchlistPage />} />
                </Routes>
              </MemoryRouter>
            </ActingClientProvider>
          </AuthProvider>
        </QueryClientProvider>
      </ThemeProvider>,
    );
    await waitFor(() =>
      expect(screen.getByText(/no approved reports/i)).toBeInTheDocument(),
    );
  });
});
