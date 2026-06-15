import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Command, CommandInput, CommandList, CommandItem, CommandGroup, CommandEmpty } from "cmdk";
import { Search } from "lucide-react";
import { Button } from "./ui/button";

const ROUTES = [
  { label: "Review Queue", href: "/queue", roles: ["reviewer"] },
  { label: "All Reports", href: "/reports", roles: ["reviewer"] },
  { label: "Dashboard", href: "/admin/dashboard", roles: ["manager", "admin"] },
  { label: "Admin Console", href: "/admin", roles: ["manager", "admin"] },
  { label: "My Reports", href: "/portal", roles: ["client_user"] },
];

/**
 * Command palette (⌘K / Ctrl+K) — accelerator, never the sole navigation path (FR-041).
 * Navigate primary surfaces; keyboard shortcut opens/closes.
 */
export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  return (
    <>
      <Button
        variant="ghost"
        size="icon"
        onClick={() => setOpen(true)}
        aria-label="Open command palette (⌘K)"
        title="Command palette (⌘K)"
      >
        <Search className="h-4 w-4" />
      </Button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-start justify-center pt-24 bg-black/50" onClick={() => setOpen(false)}>
          <div
            className="w-full max-w-lg rounded-lg border bg-card shadow-xl overflow-hidden"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-label="Command palette"
          >
            <Command>
              <div className="border-b px-3">
                <CommandInput
                  placeholder="Navigate to…"
                  className="h-12 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
                  autoFocus
                />
              </div>
              <CommandList className="max-h-64 overflow-y-auto p-2">
                <CommandEmpty>No results found.</CommandEmpty>
                <CommandGroup heading="Navigate">
                  {ROUTES.map((r) => (
                    <CommandItem
                      key={r.href}
                      value={r.label}
                      className="flex items-center gap-2 rounded px-3 py-2 text-sm cursor-pointer hover:bg-muted aria-selected:bg-muted"
                      onSelect={() => {
                        navigate(r.href);
                        setOpen(false);
                      }}
                    >
                      {r.label}
                    </CommandItem>
                  ))}
                </CommandGroup>
              </CommandList>
            </Command>
          </div>
        </div>
      )}
    </>
  );
}
