import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "@/theme/ThemeProvider";
import { AuthProvider, useAuth } from "@/auth/AuthContext";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { RequireRole } from "@/components/RequireRole";
import { http, HttpResponse } from "msw";
import { server } from "./msw/server";

function TestApp({
  roles,
  initialEntries = ["/protected"],
}: {
  roles: string[];
  initialEntries?: string[];
}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <ThemeProvider>
      <QueryClientProvider client={qc}>
        <AuthProvider>
          <MemoryRouter initialEntries={initialEntries}>
            <Routes>
              <Route path="/login" element={<div>Login page</div>} />
              <Route path="/queue" element={<div>Queue page</div>} />
              <Route path="/portal" element={<div>Portal page</div>} />
              <Route
                path="/protected"
                element={
                  <RequireRole roles={roles}>
                    <div>Protected content</div>
                  </RequireRole>
                }
              />
            </Routes>
          </MemoryRouter>
        </AuthProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}

describe("RequireRole", () => {
  it("redirects to /login when unauthenticated", async () => {
    render(<TestApp roles={["reviewer"]} />);
    await waitFor(() =>
      expect(screen.getByText("Login page")).toBeInTheDocument(),
    );
  });

  it("allows access when the user has the required role", async () => {
    // Pre-seed localStorage for a reviewer session
    localStorage.setItem("pantera_token", "test-token");
    localStorage.setItem(
      "pantera_user",
      JSON.stringify({
        id: 1,
        email: "reviewer@example.com",
        role: "reviewer",
        user_type: "staff",
        client_id: null,
        is_active: true,
      }),
    );
    render(<TestApp roles={["reviewer"]} />);
    await waitFor(() =>
      expect(screen.getByText("Protected content")).toBeInTheDocument(),
    );
    localStorage.clear();
  });

  it("blocks access and redirects to role default when wrong role", async () => {
    localStorage.setItem("pantera_token", "test-token");
    localStorage.setItem(
      "pantera_user",
      JSON.stringify({
        id: 2,
        email: "client@example.com",
        role: null,
        user_type: "client",
        client_id: 5,
        is_active: true,
      }),
    );
    render(<TestApp roles={["reviewer"]} />);
    // client_user redirected away from reviewer-only route
    await waitFor(() =>
      expect(screen.queryByText("Protected content")).not.toBeInTheDocument(),
    );
    localStorage.clear();
  });
});
