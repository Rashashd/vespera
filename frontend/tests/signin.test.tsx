import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { QueryClient } from "@tanstack/react-query";
import { server } from "./msw/server";
import { AuthProvider } from "@/auth/AuthContext";
import { ThemeProvider } from "@/theme/ThemeProvider";
import SignIn from "@/pages/SignIn";

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => vi.fn(),
    useLocation: () => ({ state: null, pathname: "/login" }),
  };
});

function renderSignIn() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <ThemeProvider>
      <QueryClientProvider client={qc}>
        <AuthProvider>
          <MemoryRouter>
            <SignIn />
          </MemoryRouter>
        </AuthProvider>
      </QueryClientProvider>
    </ThemeProvider>,
  );
}

describe("SignIn", () => {
  it("renders the sign-in form", () => {
    renderSignIn();
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();
  });

  it("shows a generic error on invalid credentials — does not leak email existence", async () => {
    server.use(
      http.post("http://localhost:8000/auth/jwt/login", () =>
        HttpResponse.json({ detail: "LOGIN_BAD_CREDENTIALS" }, { status: 400 }),
      ),
    );
    renderSignIn();
    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "bad@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "wrongpassword" },
    });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Invalid email or password.",
      ),
    );
    // Must not mention email, account, or existence
    expect(screen.getByRole("alert").textContent).not.toMatch(/account|exist|not found/i);
  });

  it("shows rate-limit message on 429", async () => {
    server.use(
      http.post("http://localhost:8000/auth/jwt/login", () =>
        HttpResponse.json({ detail: "Too many requests" }, { status: 429 }),
      ),
    );
    renderSignIn();
    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "user@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password" },
    });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/too many/i),
    );
  });
});
