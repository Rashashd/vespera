import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "@/theme/ThemeProvider";
import { AuthProvider } from "@/auth/AuthContext";
import { CommandPalette } from "@/components/CommandPalette";

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => vi.fn() };
});

// The palette is role-filtered, so seed a reviewer so its routes are visible.
const REVIEWER = {
  id: 1, email: "rev@example.com", role: "reviewer",
  user_type: "staff", client_id: null, is_active: true,
};

beforeEach(() => {
  localStorage.setItem("pantera_token", "token");
  localStorage.setItem("pantera_user", JSON.stringify(REVIEWER));
});

function TestWrapper() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <MemoryRouter>
          <CommandPalette />
        </MemoryRouter>
      </AuthProvider>
    </ThemeProvider>
  );
}

describe("CommandPalette", () => {
  it("opens on ⌘K keyboard shortcut", () => {
    render(<TestWrapper />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("closes on Escape", () => {
    render(<TestWrapper />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows role-appropriate navigation options when open", () => {
    render(<TestWrapper />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    // Reviewer sees their own surfaces…
    expect(screen.getByText("Review Queue")).toBeInTheDocument();
    expect(screen.getByText("All Reports")).toBeInTheDocument();
    // …but not manager/admin-only routes.
    expect(screen.queryByText("Dashboard")).not.toBeInTheDocument();
    expect(screen.queryByText("Clients")).not.toBeInTheDocument();
  });

  it("opens via button click", () => {
    render(<TestWrapper />);
    fireEvent.click(screen.getByRole("button", { name: /command palette/i }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
