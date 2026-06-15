import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "@/theme/ThemeProvider";
import { CommandPalette } from "@/components/CommandPalette";

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => vi.fn() };
});

function TestWrapper() {
  return (
    <ThemeProvider>
      <MemoryRouter>
        <CommandPalette />
      </MemoryRouter>
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

  it("shows navigation options when open", () => {
    render(<TestWrapper />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(screen.getByText("Review Queue")).toBeInTheDocument();
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
  });

  it("opens via button click", () => {
    render(<TestWrapper />);
    fireEvent.click(screen.getByRole("button", { name: /command palette/i }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
