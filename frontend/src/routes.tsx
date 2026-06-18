import { createBrowserRouter, Navigate } from "react-router-dom";
import { lazy, Suspense } from "react";
import { RequireRole } from "@/components/RequireRole";
import { AppShell } from "@/components/AppShell";

// Lazy-load all pages to reduce initial bundle size
const SignIn = lazy(() => import("@/pages/SignIn"));
const ReviewerQueue = lazy(() => import("@/pages/ReviewerQueue"));
const AllReports = lazy(() => import("@/pages/AllReports"));
const ReportDetailPage = lazy(() => import("@/pages/ReportDetailPage"));
const AdminConsole = lazy(() => import("@/pages/AdminConsole"));
const Costs = lazy(() => import("@/pages/Costs"));
const FailedQueue = lazy(() => import("@/pages/FailedQueue"));
const DashboardPage = lazy(() => import("@/pages/DashboardPage"));
const GlobalOverview = lazy(() => import("@/pages/GlobalOverview"));
const AuditLog = lazy(() => import("@/pages/AuditLog"));
const Clients = lazy(() => import("@/pages/Clients"));
const ClientPortal = lazy(() => import("@/pages/ClientPortal"));
const WatchlistPage = lazy(() => import("@/pages/WatchlistPage"));

function Loading() {
  return (
    <div className="flex h-full items-center justify-center text-muted-foreground">
      Loading…
    </div>
  );
}

export const router = createBrowserRouter([
  {
    path: "/login",
    element: (
      <Suspense fallback={<Loading />}>
        <SignIn />
      </Suspense>
    ),
  },
  {
    path: "/",
    element: <AppShell />,
    children: [
      // Reviewer surfaces
      {
        path: "queue",
        element: (
          <RequireRole roles={["reviewer"]}>
            <Suspense fallback={<Loading />}>
              <ReviewerQueue />
            </Suspense>
          </RequireRole>
        ),
      },
      {
        path: "queue/:reportId",
        element: (
          <RequireRole roles={["reviewer"]}>
            <Suspense fallback={<Loading />}>
              <ReportDetailPage mode="queue" />
            </Suspense>
          </RequireRole>
        ),
      },
      {
        path: "reports",
        element: (
          <RequireRole roles={["reviewer"]}>
            <Suspense fallback={<Loading />}>
              <AllReports />
            </Suspense>
          </RequireRole>
        ),
      },
      {
        path: "reports/:reportId",
        element: (
          <RequireRole roles={["reviewer"]}>
            <Suspense fallback={<Loading />}>
              <ReportDetailPage mode="all-reports" />
            </Suspense>
          </RequireRole>
        ),
      },
      // Manager-only surfaces (client lifecycle + cost dashboards)
      {
        path: "clients",
        element: (
          <RequireRole roles={["manager"]}>
            <Suspense fallback={<Loading />}>
              <Clients />
            </Suspense>
          </RequireRole>
        ),
      },
      {
        path: "costs",
        element: (
          <RequireRole roles={["manager"]}>
            <Suspense fallback={<Loading />}>
              <Costs />
            </Suspense>
          </RequireRole>
        ),
      },
      {
        path: "admin/overview",
        element: (
          <RequireRole roles={["manager"]}>
            <Suspense fallback={<Loading />}>
              <GlobalOverview />
            </Suspense>
          </RequireRole>
        ),
      },
      {
        path: "admin/dashboard",
        element: (
          <RequireRole roles={["manager"]}>
            <Suspense fallback={<Loading />}>
              <DashboardPage />
            </Suspense>
          </RequireRole>
        ),
      },
      // Admin console — manager + admin (manage existing clients' watchlists/keywords)
      {
        path: "admin",
        element: (
          <RequireRole roles={["manager", "admin"]}>
            <Suspense fallback={<Loading />}>
              <AdminConsole />
            </Suspense>
          </RequireRole>
        ),
      },
      {
        path: "audit",
        element: (
          <RequireRole roles={["manager", "admin"]}>
            <Suspense fallback={<Loading />}>
              <AuditLog />
            </Suspense>
          </RequireRole>
        ),
      },
      {
        path: "failed-queue",
        element: (
          <RequireRole roles={["manager", "admin"]}>
            <Suspense fallback={<Loading />}>
              <FailedQueue />
            </Suspense>
          </RequireRole>
        ),
      },
      // Client portal
      {
        path: "portal",
        element: (
          <RequireRole roles={["client_user"]}>
            <Suspense fallback={<Loading />}>
              <ClientPortal />
            </Suspense>
          </RequireRole>
        ),
      },
      {
        path: "portal/watchlists/:watchlistId",
        element: (
          <RequireRole roles={["client_user"]}>
            <Suspense fallback={<Loading />}>
              <WatchlistPage />
            </Suspense>
          </RequireRole>
        ),
      },
      {
        path: "portal/reports/:reportId",
        element: (
          <RequireRole roles={["client_user"]}>
            <Suspense fallback={<Loading />}>
              <ReportDetailPage mode="portal" />
            </Suspense>
          </RequireRole>
        ),
      },
      // Root redirect — shell renders the role-appropriate default
      { index: true, element: <Navigate to="/queue" replace /> },
    ],
  },
  // Catch-all
  { path: "*", element: <Navigate to="/" replace /> },
]);
