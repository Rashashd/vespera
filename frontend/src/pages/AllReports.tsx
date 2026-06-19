import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAllReports } from "@/api/hooks";
import { useActingClient } from "@/auth/ActingClientContext";
import { DeliveryStatusChip } from "@/components/DeliveryStatusChip";
import { ReportStatusBadge } from "@/components/ReportStatusBadge";
import { Button } from "@/components/ui/button";

export default function AllReports() {
  const navigate = useNavigate();
  const { clientId } = useActingClient();
  const [page, setPage] = useState(0);
  const limit = 50;
  const { data: reports = [], isLoading, isError } = useAllReports(clientId, page, limit);

  return (
    <div className="space-y-5">
      <p className="text-sm text-muted-foreground">
        Read-only view of all report statuses.
      </p>

      {!clientId && <p className="text-muted-foreground">Select a client.</p>}
      {isLoading && <p className="text-muted-foreground">Loading…</p>}
      {isError && <p className="text-destructive">Failed to load reports.</p>}

      {reports.length === 0 && !isLoading && clientId && (
        <div className="rounded-2xl border bg-card p-10 text-center text-muted-foreground shadow-sm">
          No reports found.
        </div>
      )}

      <ol className="space-y-3">
        {reports.map((r) => (
          <li key={r.id}>
            <button
              type="button"
              className="w-full rounded-xl border bg-card p-4 text-left shadow-sm transition-colors hover:border-primary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => navigate(`/reports/${r.id}`)}
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
                    {r.corroboration_count} source{r.corroboration_count !== 1 ? "s" : ""}
                  </p>
                </div>
                <div className="flex flex-col items-end gap-2">
                  {r.delivery_status && r.delivery_status !== "not_applicable" && (
                    <DeliveryStatusChip status={r.status} deliveryStatus={r.delivery_status} />
                  )}
                  <ReportStatusBadge status={r.status} />
                </div>
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
