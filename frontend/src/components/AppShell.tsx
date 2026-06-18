import { useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  BarChart3,
  Building2,
  ClipboardList,
  DollarSign,
  LayoutDashboard,
  List,
  LogOut,
  PanelLeftClose,
  PanelLeftOpen,
  ScrollText,
  ServerCrash,
  Settings,
  Shield,
} from "lucide-react";
import { useAuth } from "@/auth/AuthContext";
import { PantherMark } from "./PantherMark";
import { Wordmark } from "./Wordmark";
import { ActingClientSwitcher } from "./ActingClientSwitcher";
import { ThemeToggle } from "./ThemeToggle";
import { Button } from "./ui/button";
import { cn } from "@/lib/utils";
import { CommandPalette } from "./CommandPalette";

interface NavItem {
  label: string;
  href: string;
  icon: React.ReactNode;
  roles: string[];
  /** Match this route exactly (so a parent route isn't flagged active on child paths). */
  end?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  {
    label: "Review Queue",
    href: "/queue",
    icon: <ClipboardList className="h-5 w-5" />,
    roles: ["reviewer"],
  },
  {
    label: "All Reports",
    href: "/reports",
    icon: <List className="h-5 w-5" />,
    roles: ["reviewer"],
  },
  {
    label: "Overview",
    href: "/admin/overview",
    icon: <BarChart3 className="h-5 w-5" />,
    roles: ["manager"],
  },
  {
    label: "Dashboard",
    href: "/admin/dashboard",
    icon: <LayoutDashboard className="h-5 w-5" />,
    roles: ["manager"],
  },
  {
    label: "Costs",
    href: "/costs",
    icon: <DollarSign className="h-5 w-5" />,
    roles: ["manager"],
  },
  {
    label: "Clients",
    href: "/clients",
    icon: <Building2 className="h-5 w-5" />,
    roles: ["manager"],
  },
  {
    label: "Admin Console",
    href: "/admin",
    icon: <Settings className="h-5 w-5" />,
    roles: ["manager", "admin"],
    end: true,
  },
  {
    label: "Audit Log",
    href: "/audit",
    icon: <ScrollText className="h-5 w-5" />,
    roles: ["manager", "admin"],
  },
  {
    label: "Failed Queue",
    href: "/failed-queue",
    icon: <ServerCrash className="h-5 w-5" />,
    roles: ["manager", "admin"],
  },
  {
    label: "My Reports",
    href: "/portal",
    icon: <Shield className="h-5 w-5" />,
    roles: ["client_user"],
  },
];

function useUserRole(): string {
  const { user } = useAuth();
  if (!user) return "";
  if (user.user_type === "client") return "client_user";
  return user.role ?? "";
}

function roleLabel(role: string): string {
  return (
    { manager: "Manager", admin: "Admin", reviewer: "Reviewer", client_user: "Client" }[
      role
    ] ?? "User"
  );
}

function initialsFromEmail(email: string): string {
  const local = email.split("@")[0] ?? email;
  const parts = local.split(/[._-]+/).filter(Boolean);
  const raw =
    parts.length >= 2 ? parts[0][0] + parts[1][0] : local.slice(0, 2);
  return raw.toUpperCase();
}

/** Human page title for the top bar, derived from the active route. */
function pageTitle(pathname: string): string {
  if (/^\/(queue|reports|portal\/reports)\/\d+/.test(pathname)) return "Report";
  if (/^\/portal\/watchlists\/\d+/.test(pathname)) return "Watchlist";
  if (pathname.startsWith("/queue")) return "Review Queue";
  if (pathname.startsWith("/reports")) return "All Reports";
  if (pathname.startsWith("/admin/overview")) return "Overview";
  if (pathname.startsWith("/admin/dashboard")) return "Dashboard";
  if (pathname.startsWith("/admin")) return "Admin Console";
  if (pathname.startsWith("/costs")) return "Costs";
  if (pathname.startsWith("/clients")) return "Clients";
  if (pathname.startsWith("/audit")) return "Audit Log";
  if (pathname.startsWith("/failed-queue")) return "Failed Queue";
  if (pathname.startsWith("/portal")) return "My Reports";
  return "Pantera";
}

export function AppShell() {
  const { user, clearAuth } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const role = useUserRole();
  const isStaff = user?.user_type === "staff";

  // Auto-collapse on report-detail routes (layout C rail collision avoidance)
  const isDetailRoute =
    /^\/(queue|reports|portal\/reports)\/\d+/.test(location.pathname);
  const [collapsed, setCollapsed] = useState(isDetailRoute);

  const visibleItems = NAV_ITEMS.filter((item) => item.roles.includes(role));

  const handleLogout = () => {
    clearAuth();
    navigate("/login");
  };

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* ░░ Sidebar ░░ */}
      <aside
        className={cn(
          "flex flex-col border-r bg-card transition-all duration-200",
          collapsed ? "w-[68px]" : "w-[248px]",
        )}
        aria-label="Primary navigation"
      >
        {/* Logo + collapse toggle */}
        <div
          className={cn(
            "flex h-16 items-center px-3",
            collapsed ? "justify-center" : "justify-between",
          )}
        >
          {collapsed ? (
            <Link to="/" aria-label="Pantera home">
              <PantherMark className="h-11 w-11" />
            </Link>
          ) : (
            <Link to="/" aria-label="Pantera home" className="text-foreground">
              <Wordmark iconClassName="h-12 w-12" textClassName="text-xl" />
            </Link>
          )}
          {!collapsed && (
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setCollapsed(true)}
              aria-label="Collapse sidebar"
            >
              <PanelLeftClose className="h-4 w-4" />
            </Button>
          )}
        </div>

        {collapsed && (
          <div className="flex justify-center pb-1">
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setCollapsed(false)}
              aria-label="Expand sidebar"
            >
              <PanelLeftOpen className="h-4 w-4" />
            </Button>
          </div>
        )}

        {/* Nav items */}
        <nav className="flex-1 space-y-1 overflow-y-auto px-2 py-3" aria-label="Main navigation">
          {visibleItems.map((item) => (
            <NavLink
              key={item.href}
              to={item.href}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2.5 text-[13.5px] font-medium transition-colors",
                  isActive
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                  collapsed && "justify-center px-0",
                )
              }
              aria-label={collapsed ? item.label : undefined}
              title={collapsed ? item.label : undefined}
            >
              {item.icon}
              {!collapsed && <span className="truncate">{item.label}</span>}
            </NavLink>
          ))}
        </nav>

        {/* User block + logout */}
        <div className="border-t p-3">
          {user && (
            <div
              className={cn(
                "flex items-center gap-3",
                collapsed && "flex-col gap-2",
              )}
            >
              <span
                className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-primary/12 font-mono text-[11px] font-medium uppercase text-primary"
                aria-hidden="true"
              >
                {initialsFromEmail(user.email)}
              </span>
              {!collapsed && (
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] font-medium text-foreground">
                    {user.email}
                  </p>
                  <p className="truncate font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                    {roleLabel(role)}
                  </p>
                </div>
              )}
              <Button
                variant="ghost"
                size="icon"
                className="flex-shrink-0 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                onClick={handleLogout}
                aria-label="Sign out"
              >
                <LogOut className="h-4 w-4" />
              </Button>
            </div>
          )}
        </div>
      </aside>

      {/* ░░ Main area ░░ */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Top bar */}
        <header className="flex h-16 items-center gap-3 border-b bg-card px-7">
          <h1 className="font-display text-xl font-semibold text-foreground">
            {pageTitle(location.pathname)}
          </h1>

          <div className="flex-1" />

          {/* Acting client switcher (staff only) */}
          {isStaff && <ActingClientSwitcher />}
          <ThemeToggle />
          <CommandPalette />
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-auto p-7">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
