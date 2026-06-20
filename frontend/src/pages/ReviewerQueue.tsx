import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { AlertTriangle } from "lucide-react";
import { useReportsQueue } from "@/api/hooks";
import { useActingClient } from "@/auth/ActingClientContext";
import { SlaCountdown } from "@/components/SlaCountdown";
import { ReportStatusBadge } from "@/components/ReportStatusBadge";
import { SeverityBadge } from "@/components/SeverityBadge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { ReportSummary } from "@/api/schemas";

function sortQueue(reports: ReportSummary[]): ReportSummary[] {
  return [...reports].sort((a, b) => {
    // Expedited first
    const aExp = a.report_type === "expedited" ? 0 : 1;
    const bExp = b.report_type === "expedited" ? 0 : 1;
    if (aExp !== bExp) return aExp - bExp;
    // Then SLA ascending (overdue first)
    const aSla = a.sla_deadline ? new Date(a.sla_deadline).getTime() : Infinity;
    const bSla = b.sla_deadline ? new Date(b.sla_deadline).getTime() : Infinity;
    if (aSla !== bSla) return aSla - bSla;
    // Then created_at ascending
    return new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
  });
}

export default function ReviewerQueue() {
  const navigate = useNavigate();
  const { clientId } = useActingClient();
  const [page, setPage] = useState(0);
  const limit = 50;
  const { data: raw = [], isLoading, isError } = useReportsQueue(clientId, page, limit);

  const sorted = sortQueue(raw);
  const overdueCount = sorted.filter(
    (r) => r.report_type === "expedited" && r.sla_deadline && new Date(r.sla_deadline) < new Date(),
  ).length;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Expedited first, then by review deadline.
        </p>
        {overdueCount > 0 && (
          <div
            className="flex items-center gap-1.5 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-1.5 text-sm font-medium text-destructive"
            role="status"
            aria-live="polite"
          >
            <AlertTriangle className="h-4 w-4" />
            {overdueCount} overdue report{overdueCount !== 1 ? "s" : ""}
          </div>
        )}
      </div>

      {!clientId && (
        <p className="text-muted-foreground">Select a client to view the queue.</p>
      )}
      {isLoading && <p className="text-muted-foreground">Loading…</p>}
      {isError && <p className="text-destructive">Failed to load queue.</p>}

      {sorted.length === 0 && !isLoading && clientId && (
        <div className="rounded-2xl border bg-card p-10 text-center text-muted-foreground shadow-sm">
          Queue is empty — no reports awaiting review.
        </div>
      )}

      <ol className="space-y-3">
        {sorted.map((r) => {
          const isExpedited = r.report_type === "expedited";
          const isOverdue =
            isExpedited && r.sla_deadline && new Date(r.sla_deadline) < new Date();
          return (
            <li key={r.id}>
              <button
                type="button"
                className={cn(
                  "w-full rounded-xl border border-l-4 bg-card p-4 text-left shadow-sm transition-colors hover:border-primary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  isExpedited ? "border-l-[#b07a1e] dark:border-l-[#d9a441]" : "border-l-primary/40",
                  isOverdue && "border-l-destructive",
                )}
                onClick={() => navigate(`/queue/${r.id}`)}
                aria-label={`Report ${r.id}, ${r.report_type}, status ${r.status}`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 space-y-1.5">
                    <div className="flex items-center gap-2">
                      {r.severity && <SeverityBadge bucket={r.severity} />}
                      <span className="font-mono text-[10.5px] uppercase tracking-[0.14em] text-[#4a6580] dark:text-[#8095a8]">
                        {r.report_type}
                      </span>
                    </div>
                    <p className="font-display text-[15px] font-semibold text-foreground">
                      Report #{r.id}
                    </p>
                    <p className="text-[12.5px] text-muted-foreground">
                      {r.corroboration_count} corroborating source
                      {r.corroboration_count !== 1 ? "s" : ""} · {r.revision_count} revision
                      {r.revision_count !== 1 ? "s" : ""}
                    </p>
                  </div>
                  <div className="flex flex-col items-end gap-2">
                    {isExpedited && <SlaCountdown deadline={r.sla_deadline} />}
                    <ReportStatusBadge status={r.status} />
                  </div>
                </div>
              </button>
            </li>
          );
        })}
      </ol>

      {/* Pagination */}
      {(raw.length === limit || page > 0) && (
        <div className="flex gap-2 justify-end">
          <Button
            variant="outline"
            size="sm"
            disabled={page === 0}
            onClick={() => setPage((p) => p - 1)}
          >
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={raw.length < limit}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </Button>
        </div>
      )}
    </div>
  );
}
