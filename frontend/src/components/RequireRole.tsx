import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import type { User } from "@/api/schemas";

interface Props {
  roles: string[];
  children: React.ReactNode;
}

function defaultLandingFor(user: User): string {
  if (!user.role && user.user_type === "client") return "/portal";
  switch (user.role) {
    case "reviewer":
      return "/queue";
    case "manager":
      return "/admin/dashboard";
    case "admin":
      // Admins manage existing clients' watchlists/keywords; no client lifecycle or costs.
      return "/admin";
    default:
      return "/login";
  }
}

export function RequireRole({ roles, children }: Props) {
  const { token, user } = useAuth();
  const location = useLocation();

  if (!token || !user) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  const userRole = user.user_type === "client" ? "client_user" : (user.role ?? "");
  const allowed = roles.includes(userRole) || roles.includes(user.role ?? "");

  if (!allowed) {
    return <Navigate to={defaultLandingFor(user)} replace />;
  }

  return <>{children}</>;
}

export { defaultLandingFor };
