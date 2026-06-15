import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAllReports } from "@/api/hooks";
import { useActingClient } from "@/auth/ActingClientContext";
import { DeliveryStatusChip } from "@/components/DeliveryStatusChip";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export default function AllReports() {
  const navigate = useNavigate();
  const { clientId } = useActingClient();
  const [page, setPage] = useState(0);
  const limit = 50;
  const { data: reports = [], isLoading, isError } = useAllReports(clientId, page, limit);

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">All Reports</h1>
      <p className="text-sm text-muted-foreground">Read-only view of all report statuses.</p>

      {!clientId && <p className="text-muted-foreground">Select a client.</p>}
      {isLoading && <p className="text-muted-foreground">Loading…</p>}
      {isError && <p className="text-destructive">Failed to load reports.</p>}

      {reports.length === 0 && !isLoading && clientId && (
        <div className="rounded border bg-muted/50 p-8 text-center text-muted-foreground">
          No reports found.
        </div>
      )}

      <ol className="space-y-2">
        {reports.map((r) => (
          <li key={r.id}>
            <button
              type="button"
              className="w-full text-left rounded border bg-card p-4 transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => navigate(`/reports/${r.id}`)}
              aria-label={`Report ${r.id}`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="space-y-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-medium text-sm">#{r.id}</span>
                    <Badge variant="outline" className="capitalize text-xs">
                      {r.report_type}
                    </Badge>
                    <Badge variant="muted" className="capitalize text-xs">
                      {r.status.replace(/_/g, " ")}
                    </Badge>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {r.corroboration_count} source{r.corroboration_count !== 1 ? "s" : ""}
                  </p>
                </div>
                <DeliveryStatusChip status={r.status} />
              </div>
            </button>
          </li>
        ))}
      </ol>

      {(reports.length === limit || page > 0) && (
        <div className="flex gap-2 justify-end">
          <Button variant="outline" size="sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
            Previous
          </Button>
          <Button variant="outline" size="sm" disabled={reports.length < limit} onClick={() => setPage((p) => p + 1)}>
            Next
          </Button>
        </div>
      )}
    </div>
  );
}
