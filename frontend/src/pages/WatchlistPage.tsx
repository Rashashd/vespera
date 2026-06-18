import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { usePortalReports } from "@/api/hooks";
import { useAuth } from "@/auth/AuthContext";
import { DeliveryStatusChip } from "@/components/DeliveryStatusChip";
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
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={() => navigate("/portal")} aria-label="Back to portal">
          <ArrowLeft className="mr-1 h-4 w-4" />
          Back
        </Button>
        <h1 className="font-display text-lg font-semibold text-foreground">
          Watchlist #{watchlistId} — reports
        </h1>
      </div>

      {isLoading && <p className="text-muted-foreground">Loading…</p>}
      {isError && <p className="text-destructive">Failed to load reports.</p>}

      {reports.length === 0 && !isLoading && (
        <div className="rounded-2xl border bg-card p-10 text-center text-muted-foreground shadow-sm">
          No approved reports for this watchlist yet.
        </div>
      )}

      <ol className="space-y-3">
        {reports.map((r) => (
          <li key={r.id}>
            <button
              type="button"
              className="w-full rounded-xl border bg-card p-4 text-left shadow-sm transition-colors hover:border-primary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => navigate(`/portal/reports/${r.id}`)}
              aria-label={`Report ${r.id}`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 space-y-1.5">
                  <span className="font-mono text-[10.5px] uppercase tracking-[0.14em] text-[#4a6580] dark:text-[#8095a8]">
                    {r.report_type}
                  </span>
                  <p className="font-display text-[15px] font-semibold text-foreground">
                    Report #{r.id}
                  </p>
                  <p className="text-[12.5px] text-muted-foreground">
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
