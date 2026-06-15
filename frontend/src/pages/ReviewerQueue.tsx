import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { AlertTriangle } from "lucide-react";
import { useReportsQueue } from "@/api/hooks";
import { useActingClient } from "@/auth/ActingClientContext";
import { SlaCountdown } from "@/components/SlaCountdown";
import { Badge } from "@/components/ui/badge";
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
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Review Queue</h1>
        {overdueCount > 0 && (
          <div
            className="flex items-center gap-1.5 rounded border border-red-300 bg-red-50 px-3 py-1.5 text-sm text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-400"
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
        <div className="rounded border bg-muted/50 p-8 text-center text-muted-foreground">
          Queue is empty — no reports awaiting review.
        </div>
      )}

      <ol className="space-y-2">
        {sorted.map((r) => {
          const isExpedited = r.report_type === "expedited";
          const isOverdue =
            isExpedited && r.sla_deadline && new Date(r.sla_deadline) < new Date();
          return (
            <li key={r.id}>
              <button
                type="button"
                className={cn(
                  "w-full text-left rounded border bg-card p-4 transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  isExpedited ? "border-l-4 border-l-amber-500" : "border-l-4 border-l-primary/30",
                  isOverdue && "border-l-red-600",
                )}
                onClick={() => navigate(`/queue/${r.id}`)}
                aria-label={`Report ${r.id}, ${r.report_type}, status ${r.status}`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="space-y-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-medium text-sm">#{r.id}</span>
                      <Badge
                        variant={isExpedited ? "default" : "outline"}
                        className="capitalize text-xs"
                      >
                        {r.report_type}
                      </Badge>
                      <Badge variant="muted" className="capitalize text-xs">
                        {r.status.replace(/_/g, " ")}
                      </Badge>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      {r.corroboration_count} corroborating source
                      {r.corroboration_count !== 1 ? "s" : ""} · {r.revision_count} revision
                      {r.revision_count !== 1 ? "s" : ""}
                    </p>
                  </div>
                  <div className="shrink-0">
                    {isExpedited && <SlaCountdown deadline={r.sla_deadline} />}
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
