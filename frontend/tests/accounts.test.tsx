import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { server } from "./msw/server";
import { ThemeProvider } from "@/theme/ThemeProvider";
import { AuthProvider } from "@/auth/AuthContext";
import { ActingClientProvider } from "@/auth/ActingClientContext";
import StaffPage from "@/pages/StaffPage";
import ClientUsersPage from "@/pages/ClientUsersPage";

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => vi.fn() };
});

const MANAGER_USER = {
  id: 1,
  email: "manager@example.com",
  role: "manager",
  user_type: "staff",
  client_id: null,
  is_active: true,
};

function Wrapper({ children }: { children: React.ReactNode }) {
  localStorage.setItem("pantera_token", "token");
  localStorage.setItem("pantera_user", JSON.stringify(MANAGER_USER));
  localStorage.setItem("pantera_acting_client", "1");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <ThemeProvider>
      <QueryClientProvider client={qc}>
        <AuthProvider>
          <ActingClientProvider>
            <MemoryRouter>{children}</MemoryRouter>
          </ActingClientProvider>
        </AuthProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}

describe("StaffPage", () => {
  it("shows the create form and lists existing staff", async () => {
    server.use(
      http.get("http://localhost:8000/clients", () =>
        HttpResponse.json([{ id: 1, name: "Acme", status: "active" }]),
      ),
      http.get("http://localhost:8000/staff", () =>
        HttpResponse.json([
          {
            id: 5,
            email: "reviewer@acme.test",
            role: "reviewer",
            user_type: "staff",
            is_active: true,
          },
        ]),
      ),
    );
    render(
      <Wrapper>
        <StaffPage />
      </Wrapper>,
    );
    expect(screen.getByText(/create staff user/i)).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText("reviewer@acme.test")).toBeInTheDocument(),
    );
  });
});

describe("ClientUsersPage", () => {
  it("shows the create form and lists existing client users for the acting client", async () => {
    server.use(
      http.get("http://localhost:8000/clients", () =>
        HttpResponse.json([{ id: 1, name: "Acme", status: "active" }]),
      ),
      http.get("http://localhost:8000/clients/1/users", () =>
        HttpResponse.json([
          {
            id: 9,
            email: "portal-user@acme.test",
            client_id: 1,
            role: "client_user",
            client_scope: "scoped",
            min_severity: "serious",
            watchlist_ids: [3],
            is_active: true,
          },
        ]),
      ),
      http.get("http://localhost:8000/clients/1/watchlists", () =>
        HttpResponse.json([{ id: 3, client_id: 1, name: "Statins" }]),
      ),
    );
    render(
      <Wrapper>
        <ClientUsersPage />
      </Wrapper>,
    );
    expect(screen.getByText(/create client user/i)).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText("portal-user@acme.test")).toBeInTheDocument(),
    );
  });
});
