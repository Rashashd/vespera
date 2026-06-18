import { useState } from "react";
import { toast } from "sonner";
import { Check, RotateCcw } from "lucide-react";
import { useDeadLetters, useResolveDeadLetter, useClients } from "@/api/hooks";
import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import type { DeadLetter } from "@/api/schemas";

const fmt = (iso: string) => new Date(iso).toLocaleString();

export default function FailedQueue() {
  const [showResolved, setShowResolved] = useState(false);
  const {
    data: rows = [],
    isLoading,
    isError,
  } = useDeadLetters({ resolved: showResolved });
  const { data: clients = [] } = useClients();
  const resolve = useResolveDeadLetter();

  const clientLabel = (id: number | null) =>
    id == null ? "System" : clients.find((c) => c.id === id)?.name ?? `Client ${id}`;

  const handleResolve = (dl: DeadLetter) => {
    resolve.mutate(dl.id, {
      onSuccess: () => toast.success("Marked resolved."),
      onError: (err) => {
        if (err instanceof ApiError && err.status === 409) {
          toast.info("Already resolved — list refreshed.");
        } else {
          toast.error("Failed to resolve.");
        }
      },
    });
  };

  return (
    <div className="max-w-4xl space-y-5">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          Jobs that exhausted their retries. Resolving marks one operator-triaged —
          it does not re-run it (dead-lettered jobs cannot be replayed).
        </p>
        <div className="flex flex-shrink-0 rounded-lg border bg-card p-0.5">
          <button
            type="button"
            onClick={() => setShowResolved(false)}
            className={`rounded-md px-3 py-1 text-[12.5px] font-medium transition-colors ${
              !showResolved
                ? "bg-primary/10 text-primary"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            Unresolved
          </button>
          <button
            type="button"
            onClick={() => setShowResolved(true)}
            className={`rounded-md px-3 py-1 text-[12.5px] font-medium transition-colors ${
              showResolved
                ? "bg-primary/10 text-primary"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            Resolved
          </button>
        </div>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
      {isError && (
        <p className="text-sm text-destructive">Failed to load the failed queue.</p>
      )}

      {!isLoading && !isError && rows.length === 0 && (
        <div className="rounded-2xl border bg-card p-10 text-center text-muted-foreground shadow-sm">
          {showResolved ? "No resolved failed jobs." : "No unresolved failed jobs."}
        </div>
      )}

      <ol className="space-y-3">
        {rows.map((dl) => {
          const resolved = dl.resolved_at != null;
          return (
            <li key={dl.id}>
              <div
                className={`rounded-xl border border-l-4 bg-card p-4 shadow-sm ${
                  resolved ? "border-l-muted-foreground opacity-70" : "border-l-destructive"
                }`}
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0 space-y-1.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-display text-[15px] font-semibold text-foreground">
                        {dl.error_class}
                      </span>
                      <span className="rounded-md bg-muted px-1.5 py-0.5 font-mono text-[10.5px] text-muted-foreground">
                        {dl.attempts} attempt{dl.attempts !== 1 ? "s" : ""}
                      </span>
                    </div>
                    {/* error_summary may be null (transient) — fall back to the class */}
                    <p className="text-[13px] text-muted-foreground">
                      {dl.error_summary ?? dl.error_class}
                    </p>
                    <p className="flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[11px] text-[#4a6580] dark:text-[#8095a8]">
                      <span>{dl.job_name}</span>
                      <span className="opacity-50">·</span>
                      <span>{clientLabel(dl.client_id)}</span>
                      <span className="opacity-50">·</span>
                      <span>dead-lettered {fmt(dl.dead_lettered_at)}</span>
                    </p>
                    <p className="truncate font-mono text-[10.5px] text-muted-foreground/70">
                      {dl.job_key}
                    </p>
                  </div>
                  <div className="flex-shrink-0">
                    {resolved ? (
                      <span className="inline-flex items-center gap-1.5 font-mono text-[10.5px] uppercase tracking-[0.1em] text-muted-foreground">
                        <Check className="h-3.5 w-3.5" />
                        Resolved
                      </span>
                    ) : (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleResolve(dl)}
                        disabled={resolve.isPending}
                      >
                        <RotateCcw className="mr-1 h-3 w-3" />
                        Resolve
                      </Button>
                    )}
                  </div>
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
