import { useNavigate } from "react-router-dom";
import { usePortalReports } from "@/api/hooks";
import { useWatchlists } from "@/api/hooks";
import { useAuth } from "@/auth/AuthContext";
import { DeliveryStatusChip } from "@/components/DeliveryStatusChip";
import { Badge } from "@/components/ui/badge";

export default function ClientPortal() {
  const { user } = useAuth();
  const clientId = user?.client_id ?? null;
  const navigate = useNavigate();
  const { data: watchlists = [], isLoading: wlLoading, isError: wlError } = useWatchlists(clientId);
  const { data: reports = [], isLoading: rLoading, isError: rError } = usePortalReports(clientId);

  if (!clientId) {
    return <p className="text-muted-foreground">No client associated with your account.</p>;
  }

  const isLoading = wlLoading || rLoading;
  const isError = wlError || rError;

  if (isLoading) {
    return <p className="text-muted-foreground">Loading…</p>;
  }

  if (isError) {
    return <p className="text-destructive">Failed to load portal data.</p>;
  }

  if (watchlists.length === 0) {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-semibold">My Reports</h1>
        <div className="rounded border bg-muted/50 p-8 text-center text-muted-foreground">
          No watchlists configured for your account.
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">My Reports</h1>
      <ol className="space-y-3">
        {watchlists.map((w) => {
          const wlReports = reports.filter((r) => r.watchlist_id === w.id);
          return (
            <li key={w.id}>
              <button
                type="button"
                className="w-full text-left rounded border bg-card p-4 transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() => navigate(`/portal/watchlists/${w.id}`)}
                aria-label={`View reports for watchlist ${w.name}`}
              >
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-medium text-sm">{w.name}</p>
                    <p className="text-xs text-muted-foreground">
                      {wlReports.length} report{wlReports.length !== 1 ? "s" : ""}
                    </p>
                  </div>
                  <Badge variant="outline" className="text-xs capitalize">{w.status}</Badge>
                </div>
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
