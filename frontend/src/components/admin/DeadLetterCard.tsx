import { AlertTriangle, CheckCircle2 } from "lucide-react";

/**
 * Spec 13 US7: surfaces the unresolved dead-letter count for the acting client
 * (from OpsDashboard.failed_jobs). A non-zero count flags jobs that exhausted retries
 * and need operator attention in the admin dead-letter view.
 */
export function DeadLetterCard({ count }: { count: number }) {
  const hasFailures = count > 0;
  return (
    <div
      className={
        "rounded border p-4 flex items-center gap-3 " +
        (hasFailures ? "border-destructive/40 bg-destructive/5" : "bg-card")
      }
    >
      {hasFailures ? (
        <AlertTriangle className="h-5 w-5 text-destructive shrink-0" />
      ) : (
        <CheckCircle2 className="h-5 w-5 text-muted-foreground shrink-0" />
      )}
      <div className="space-y-0.5">
        <p className="text-xs text-muted-foreground uppercase tracking-wide">Dead-letter queue</p>
        <p className="text-2xl font-semibold">{count}</p>
        <p className="text-xs text-muted-foreground">
          {hasFailures ? "unresolved failed job(s) — needs attention" : "no unresolved failed jobs"}
        </p>
      </div>
    </div>
  );
}
