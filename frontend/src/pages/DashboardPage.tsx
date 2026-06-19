import { useActingClient } from "@/auth/ActingClientContext";
import { useUsageDashboard, useOpsDashboard } from "@/api/hooks";
import { DeadLetterCard } from "@/components/admin/DeadLetterCard";

function StatCard({
  title,
  value,
  subtitle,
}: {
  title: string;
  value: string | number;
  subtitle?: string;
}) {
  return (
    <div className="rounded-2xl border bg-card p-5 shadow-sm">
      <p className="font-mono text-[10.5px] uppercase tracking-[0.14em] text-[#4a6580] dark:text-[#8095a8]">
        {title}
      </p>
      <p className="mt-2 font-display text-[28px] font-semibold leading-none text-foreground">
        {value}
      </p>
      {subtitle && (
        <p className="mt-2 text-[12px] text-[#4a6580] dark:text-[#8095a8]">{subtitle}</p>
      )}
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="font-mono text-[11px] uppercase tracking-[0.16em] text-[#4a6580] dark:text-[#8095a8]">
      {children}
    </h2>
  );
}

export default function DashboardPage() {
  const { clientId, client } = useActingClient();
  const { data: usage, isLoading: usageLoading, isError: usageError } =
    useUsageDashboard(clientId);
  const { data: ops, isLoading: opsLoading, isError: opsError } =
    useOpsDashboard(clientId);

  if (!clientId) {
    return (
      <p className="text-muted-foreground">Select a client to view the dashboard.</p>
    );
  }

  return (
    <div className="space-y-6">
      <p className="text-sm text-[#4a6580] dark:text-[#8095a8]">
        Pipeline, delivery, and cost{client ? ` — ${client.name}` : ""}.
      </p>

      {/* Pipeline status */}
      <section className="space-y-3">
        <SectionLabel>Pipeline</SectionLabel>
        {opsLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {opsError && (
          <p className="text-sm text-destructive">Failed to load pipeline metrics.</p>
        )}
        {ops && (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <StatCard
              title="Pending"
              value={ops.queue.pending}
              subtitle={`${ops.queue.expedited} expedited · ${ops.queue.batch} batch`}
            />
            <StatCard
              title="SLA overdue"
              value={ops.sla.overdue}
              subtitle={`${ops.sla.due_soon} due soon · ${ops.sla.met_pct}% met`}
            />
            <StatCard
              title="Avg revisions"
              value={ops.redraft.avg_revisions.toFixed(1)}
              subtitle={`${ops.redraft.hit_cap} at cap`}
            />
            <StatCard title="Approved" value={ops.by_status["approved"] ?? 0} />
          </div>
        )}
        {ops && <DeadLetterCard count={ops.failed_jobs ?? 0} />}
      </section>

      {/* Delivery cards (spec 13 — real delivery lifecycle) */}
      <section className="space-y-3">
        <SectionLabel>Delivery</SectionLabel>
        {opsLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {ops?.delivery && (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <StatCard title="Sent" value={ops.delivery.sent} subtitle="awaiting confirmation" />
            <StatCard title="Delivered" value={ops.delivery.delivered} subtitle="confirmed" />
            <StatCard title="Failed" value={ops.delivery.failed} subtitle="needs attention" />
            <StatCard
              title="Success rate"
              value={`${ops.delivery.success_rate}%`}
              subtitle="delivered ÷ dispatched"
            />
          </div>
        )}
        {ops && !ops.delivery && (
          <div className="rounded-xl border bg-muted/40 p-4 text-sm text-muted-foreground">
            No delivery activity recorded yet for this client.
          </div>
        )}
      </section>

      {/* Cost dashboard */}
      <section className="space-y-3">
        <SectionLabel>LLM cost</SectionLabel>
        {usageLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {usageError && (
          <p className="text-sm text-destructive">Failed to load cost data.</p>
        )}
        {usage && usage.call_count === 0 && (
          <div className="rounded-xl border bg-muted/40 p-4 text-sm text-muted-foreground">
            No LLM usage recorded yet for this client.
          </div>
        )}
        {usage && usage.call_count > 0 && (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <StatCard
              title="Total cost"
              value={`$${parseFloat(usage.total_cost_usd).toFixed(2)}`}
            />
            <StatCard title="Total calls" value={usage.call_count.toLocaleString()} />
            <StatCard
              title="Input tokens"
              value={usage.total_input_tokens.toLocaleString()}
            />
            <StatCard
              title="Output tokens"
              value={usage.total_output_tokens.toLocaleString()}
            />
          </div>
        )}
        {usage && Object.keys(usage.by_call_site).length > 0 && (
          <div className="rounded-2xl border bg-card p-5 shadow-sm">
            <p className="mb-3 font-mono text-[10.5px] uppercase tracking-[0.12em] text-[#4a6580] dark:text-[#8095a8]">
              By call site
            </p>
            <div className="space-y-2">
              {Object.entries(usage.by_call_site).map(([site, data]) => (
                <div
                  key={site}
                  className="flex items-center justify-between text-sm"
                >
                  <span className="capitalize text-foreground">
                    {site.replace(/_/g, " ")}
                  </span>
                  <span className="font-mono text-[#4a6580] dark:text-[#8095a8]">
                    ${parseFloat(data.cost_usd).toFixed(2)} · {data.calls} call
                    {data.calls !== 1 ? "s" : ""}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
