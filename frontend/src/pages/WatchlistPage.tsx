import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { usePortalReports } from "@/api/hooks";
import { useAuth } from "@/auth/AuthContext";
import { DeliveryStatusChip } from "@/components/DeliveryStatusChip";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatIso } from "@/lib/dateUtils";

export default function WatchlistPage() {
  const { watchlistId } = useParams<{ watchlistId: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const clientId = user?.client_id ?? null;
  const wid = watchlistId ? parseInt(watchlistId, 10) : undefined;

  const { data: reports = [], isLoading, isError } = usePortalReports(clientId, wid);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={() => navigate("/portal")} aria-label="Back to portal">
          <ArrowLeft className="h-4 w-4 mr-1" />
          Back
        </Button>
        <h1 className="text-xl font-semibold">Reports — Watchlist #{watchlistId}</h1>
      </div>

      {isLoading && <p className="text-muted-foreground">Loading…</p>}
      {isError && <p className="text-destructive">Failed to load reports.</p>}

      {reports.length === 0 && !isLoading && (
        <div className="rounded border bg-muted/50 p-8 text-center text-muted-foreground">
          No approved reports for this watchlist yet.
        </div>
      )}

      <ol className="space-y-2">
        {reports.map((r) => (
          <li key={r.id}>
            <button
              type="button"
              className="w-full text-left rounded border bg-card p-4 transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => navigate(`/portal/reports/${r.id}`)}
              aria-label={`Report ${r.id}`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="space-y-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-medium text-sm">#{r.id}</span>
                    <Badge variant="outline" className="capitalize text-xs">{r.report_type}</Badge>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {r.corroboration_count} source{r.corroboration_count !== 1 ? "s" : ""} · {formatIso(r.created_at)}
                  </p>
                </div>
                <DeliveryStatusChip
                  status={r.status}
                  deliveryStatus={r.delivery_status}
                />
              </div>
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}
