import { useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  ClipboardList,
  LayoutDashboard,
  List,
  LogOut,
  Menu,
  Settings,
  Shield,
  X,
} from "lucide-react";
import { useAuth } from "@/auth/AuthContext";
import { ActingClientSwitcher } from "./ActingClientSwitcher";
import { ThemeToggle } from "./ThemeToggle";
import { Button } from "./ui/button";
import { Separator } from "./ui/separator";
import { cn } from "@/lib/utils";
import { CommandPalette } from "./CommandPalette";

interface NavItem {
  label: string;
  href: string;
  icon: React.ReactNode;
  roles: string[];
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
    label: "Dashboard",
    href: "/admin/dashboard",
    icon: <LayoutDashboard className="h-5 w-5" />,
    roles: ["manager", "admin"],
  },
  {
    label: "Admin Console",
    href: "/admin",
    icon: <Settings className="h-5 w-5" />,
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
      {/* Sidebar */}
      <aside
        className={cn(
          "flex flex-col border-r bg-card transition-all duration-200",
          collapsed ? "sidebar-rail" : "w-56",
        )}
        aria-label="Primary navigation"
      >
        {/* Logo / collapse toggle */}
        <div className="flex h-14 items-center justify-between px-3">
          {!collapsed && (
            <Link to="/" className="text-base font-semibold text-primary truncate">
              Pantera PV
            </Link>
          )}
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setCollapsed((c) => !c)}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {collapsed ? <Menu className="h-4 w-4" /> : <X className="h-4 w-4" />}
          </Button>
        </div>
        <Separator />

        {/* Nav items */}
        <nav className="flex-1 overflow-y-auto py-2" aria-label="Main navigation">
          {visibleItems.map((item) => (
            <NavLink
              key={item.href}
              to={item.href}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 px-3 py-2 text-sm rounded-md mx-1 transition-colors",
                  isActive
                    ? "bg-primary/10 text-primary font-medium"
                    : "text-foreground hover:bg-muted",
                  collapsed && "justify-center",
                )
              }
              aria-label={collapsed ? item.label : undefined}
              title={collapsed ? item.label : undefined}
            >
              {item.icon}
              {!collapsed && <span>{item.label}</span>}
            </NavLink>
          ))}
        </nav>

        {/* User / logout */}
        <div className="border-t p-2">
          <Button
            variant="ghost"
            size={collapsed ? "icon" : "sm"}
            className={cn("w-full", !collapsed && "justify-start gap-2")}
            onClick={handleLogout}
            aria-label="Sign out"
          >
            <LogOut className="h-4 w-4" />
            {!collapsed && <span>Sign out</span>}
          </Button>
        </div>
      </aside>

      {/* Main area */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Top bar */}
        <header className="flex h-14 items-center gap-3 border-b bg-card px-4">
          {/* Acting client switcher (staff only) */}
          {isStaff && <ActingClientSwitcher />}

          <div className="flex-1" />

          {/* User info */}
          {user && (
            <span className="text-sm text-muted-foreground hidden md:inline">
              {user.email}
            </span>
          )}

          <ThemeToggle />
          <CommandPalette />
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
