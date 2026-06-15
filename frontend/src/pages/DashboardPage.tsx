import { useActingClient } from "@/auth/ActingClientContext";
import { useUsageDashboard, useOpsDashboard } from "@/api/hooks";

function StatCard({ title, value, subtitle }: { title: string; value: string | number; subtitle?: string }) {
  return (
    <div className="rounded border bg-card p-4 space-y-1">
      <p className="text-xs text-muted-foreground uppercase tracking-wide">{title}</p>
      <p className="text-2xl font-semibold">{value}</p>
      {subtitle && <p className="text-xs text-muted-foreground">{subtitle}</p>}
    </div>
  );
}

export default function DashboardPage() {
  const { clientId, client } = useActingClient();
  const { data: usage, isLoading: usageLoading, isError: usageError } = useUsageDashboard(clientId);
  const { data: ops, isLoading: opsLoading, isError: opsError } = useOpsDashboard(clientId);

  if (!clientId) {
    return <p className="text-muted-foreground">Select a client to view the dashboard.</p>;
  }

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">
        Dashboard{client ? ` — ${client.name}` : ""}
      </h1>

      {/* Pipeline status */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">Pipeline</h2>
        {opsLoading && <p className="text-muted-foreground text-sm">Loading…</p>}
        {opsError && <p className="text-destructive text-sm">Failed to load pipeline metrics.</p>}
        {ops && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <StatCard title="Pending" value={ops.queue.pending} subtitle={`${ops.queue.expedited} expedited · ${ops.queue.batch} batch`} />
            <StatCard title="SLA Overdue" value={ops.sla.overdue} subtitle={`${ops.sla.due_soon} due soon · ${ops.sla.met_pct}% met`} />
            <StatCard title="Avg revisions" value={ops.redraft.avg_revisions.toFixed(1)} subtitle={`${ops.redraft.hit_cap} at cap`} />
            <StatCard title="Approved" value={ops.by_status["approved"] ?? 0} />
          </div>
        )}
      </section>

      {/* Delivery cards (spec-13 forward dependency) */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">Delivery</h2>
        <div className="rounded border bg-muted/50 p-4 text-sm text-muted-foreground">
          Delivery metrics are pending the delivery layer — available once spec 13 ships.
        </div>
      </section>

      {/* Cost dashboard */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">LLM Cost</h2>
        {usageLoading && <p className="text-muted-foreground text-sm">Loading…</p>}
        {usageError && <p className="text-destructive text-sm">Failed to load cost data.</p>}
        {usage && usage.call_count === 0 && (
          <div className="rounded border bg-muted/50 p-4 text-sm text-muted-foreground">
            No LLM usage recorded yet for this client.
          </div>
        )}
        {usage && usage.call_count > 0 && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <StatCard title="Total cost" value={`$${parseFloat(usage.total_cost_usd).toFixed(4)}`} />
            <StatCard title="Total calls" value={usage.call_count} />
            <StatCard title="Input tokens" value={usage.total_input_tokens.toLocaleString()} />
            <StatCard title="Output tokens" value={usage.total_output_tokens.toLocaleString()} />
          </div>
        )}
        {usage && Object.keys(usage.by_call_site).length > 0 && (
          <div className="rounded border bg-card p-4 space-y-2">
            <p className="text-xs font-medium text-muted-foreground">By call site</p>
            {Object.entries(usage.by_call_site).map(([site, data]) => (
              <div key={site} className="flex items-center justify-between text-sm">
                <span className="capitalize">{site}</span>
                <span className="text-muted-foreground">
                  ${parseFloat(data.cost_usd).toFixed(4)} · {data.calls} call{data.calls !== 1 ? "s" : ""}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
