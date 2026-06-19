import { AlertTriangle, CheckCircle2, ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";

/**
 * Spec 13 US7: a dashboard summary of the acting client's unresolved dead-letter
 * count (from OpsDashboard.failed_jobs). Links through to the full Failed Queue
 * page for triage/resolve. A non-zero count flags jobs that exhausted retries.
 */
export function DeadLetterCard({ count }: { count: number }) {
  const hasFailures = count > 0;
  return (
    <Link
      to="/failed-queue"
      className={`flex items-center gap-3 rounded-2xl border p-5 shadow-sm transition-colors hover:border-primary/40 ${
        hasFailures ? "border-destructive/40 bg-destructive/5" : "bg-card"
      }`}
    >
      {hasFailures ? (
        <AlertTriangle className="h-5 w-5 flex-shrink-0 text-destructive" />
      ) : (
        <CheckCircle2 className="h-5 w-5 flex-shrink-0 text-muted-foreground" />
      )}
      <div className="min-w-0 flex-1">
        <p className="font-mono text-[10.5px] uppercase tracking-[0.14em] text-[#4a6580] dark:text-[#8095a8]">
          Dead-letter queue
        </p>
        <p className="font-display text-[22px] font-semibold leading-none text-foreground">
          {count}
        </p>
        <p className="mt-1 text-[12px] text-[#4a6580] dark:text-[#8095a8]">
          {hasFailures
            ? "unresolved failed jobs — open Failed Queue"
            : "no unresolved failed jobs"}
        </p>
      </div>
      <ChevronRight className="h-4 w-4 flex-shrink-0 text-muted-foreground" aria-hidden="true" />
    </Link>
  );
}
