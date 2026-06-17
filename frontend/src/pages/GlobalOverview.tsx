import { useQueries } from "@tanstack/react-query";
import { Clock, AlertTriangle, CheckCircle2, DollarSign } from "lucide-react";
import { get } from "@/api/client";
import {
  OpsDashboardSchema,
  CostDashboardSchema,
  type OpsDashboard,
  type CostDashboard,
} from "@/api/schemas";
import { useClients, useAuditLog } from "@/api/hooks";

interface ClientMetrics {
  ops: OpsDashboard | null;
  cost: CostDashboard | null;
}

function Panel({
  title,
  aside,
  children,
}: {
  title: string;
  aside?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-2xl border bg-card p-5 shadow-sm">
      <div className="mb-4 flex items-baseline justify-between gap-3">
        <h2 className="text-[15px] font-semibold text-foreground">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

function Kpi({
  icon,
  label,
  value,
  hint,
  dot,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  hint: string;
  dot: string;
}) {
  return (
    <div className="rounded-2xl border bg-card p-5 shadow-sm">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-[#4a6580] dark:text-[#8095a8]">
          {icon}
          <span className="font-mono text-[10.5px] uppercase tracking-[0.14em]">
            {label}
          </span>
        </div>
        <span className={`h-2 w-2 rounded-full ${dot}`} aria-hidden="true" />
      </div>
      <p className="mt-3 font-display text-[30px] font-semibold leading-none text-foreground">
        {value}
      </p>
      <p className="mt-2 text-[12px] text-[#4a6580] dark:text-[#8095a8]">{hint}</p>
    </div>
  );
}

const TIME_FMT = new Intl.DateTimeFormat(undefined, {
  hour: "2-digit",
  minute: "2-digit",
});

function humanize(action: string): string {
  const s = action.replace(/[._]+/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export default function GlobalOverview() {
  const { data: clients = [], isLoading: clientsLoading } = useClients();
  const { data: auditRows = [] } = useAuditLog({});

  // One ops + one cost query per client, run in parallel.
  const opsQueries = useQueries({
    queries: clients.map((c) => ({
      queryKey: ["metrics", c.id],
      queryFn: () =>
        get<unknown>(`/clients/${c.id}/metrics`).then((r) =>
          OpsDashboardSchema.parse(r),
        ),
    })),
  });
  const costQueries = useQueries({
    queries: clients.map((c) => ({
      queryKey: ["usage", c.id],
      queryFn: () =>
        get<unknown>(`/clients/${c.id}/usage`).then((r) =>
          CostDashboardSchema.parse(r),
        ),
    })),
  });

  const loading =
    clientsLoading ||
    opsQueries.some((q) => q.isLoading) ||
    costQueries.some((q) => q.isLoading);

  const perClient: (ClientMetrics & { id: number; name: string })[] = clients.map(
    (c, i) => ({
      id: c.id,
      name: c.name,
      ops: opsQueries[i]?.data ?? null,
      cost: costQueries[i]?.data ?? null,
    }),
  );

  // Aggregate totals.
  const totalPending = perClient.reduce(
    (s, c) => s + (c.ops?.queue.pending ?? 0),
    0,
  );
  const totalDueSoon = perClient.reduce(
    (s, c) => s + (c.ops?.sla.due_soon ?? 0),
    0,
  );
  const totalCost = perClient.reduce(
    (s, c) => s + Number(c.cost?.total_cost_usd ?? 0),
    0,
  );

  // Report counts across all clients, keyed by ReportStatus.
  const byStatus = perClient.reduce<Record<string, number>>((acc, c) => {
    const bs = c.ops?.by_status ?? {};
    for (const k of Object.keys(bs)) acc[k] = (acc[k] ?? 0) + bs[k];
    return acc;
  }, {});
  const cycle = {
    approved: byStatus.approved ?? 0,
    // Delivery lifecycle (sent/delivered/delivery_failed) lands in spec 13 —
    // shown as 0 placeholders until then.
    delivered: 0,
    pending: (byStatus.drafted ?? 0) + (byStatus.under_review ?? 0),
    sentBack: (byStatus.rejected ?? 0) + (byStatus.needs_manual_revision ?? 0),
    failed: 0,
  };

  // Cost-per-client bars (sorted high → low).
  const costRows = perClient
    .map((c) => ({ name: c.name, cost: Number(c.cost?.total_cost_usd ?? 0) }))
    .sort((a, b) => b.cost - a.cost);
  const maxCost = Math.max(1, ...costRows.map((r) => r.cost));

  const legend: { label: string; count: number; color: string }[] = [
    { label: "Approved", count: cycle.approved, color: "bg-primary" },
    { label: "Delivered", count: cycle.delivered, color: "bg-[#4a6fa0] dark:bg-[#6e9fc4]" },
    { label: "Pending", count: cycle.pending, color: "bg-[#b07a1e] dark:bg-[#d9a441]" },
    { label: "Sent back", count: cycle.sentBack, color: "bg-[#a33a36] dark:bg-[#c0706c]" },
    { label: "Failed", count: cycle.failed, color: "bg-destructive" },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-[22px] font-semibold text-foreground">
          Platform overview
        </h1>
        <p className="text-sm text-[#4a6580] dark:text-[#8095a8]">
          Totals across all clients.
        </p>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Kpi
          icon={<Clock className="h-4 w-4" />}
          label="Pending review"
          value={String(totalPending)}
          hint="awaiting reviewer"
          dot="bg-primary"
        />
        <Kpi
          icon={<AlertTriangle className="h-4 w-4" />}
          label="Urgent · due soon"
          value={String(totalDueSoon)}
          hint="expedited, awaiting review"
          dot="bg-[#b07a1e] dark:bg-[#d9a441]"
        />
        <Kpi
          icon={<CheckCircle2 className="h-4 w-4" />}
          label="Approved · cycle"
          value={String(cycle.approved)}
          hint="approved this cycle"
          dot="bg-primary"
        />
        <Kpi
          icon={<DollarSign className="h-4 w-4" />}
          label="Cost · MTD"
          value={`$${totalCost.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
          hint={`across ${clients.length} client${clients.length === 1 ? "" : "s"}`}
          dot="bg-[#4a6fa0] dark:bg-[#6e9fc4]"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Cost per client */}
        <Panel
          title="Cost per client · MTD"
          aside={
            <span className="font-mono text-[12px] text-[#4a6580] dark:text-[#8095a8]">
              ${totalCost.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} total
            </span>
          }
        >
          {loading && costRows.length === 0 ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : costRows.length === 0 ? (
            <p className="text-sm text-muted-foreground">No clients yet.</p>
          ) : (
            <div className="space-y-4">
              {costRows.map((r) => (
                <div key={r.name}>
                  <div className="mb-1.5 flex items-center justify-between text-[13px]">
                    <span className="text-foreground">{r.name}</span>
                    <span className="font-mono text-[#4a6580] dark:text-[#8095a8]">
                      ${r.cost.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full bg-primary"
                      style={{ width: `${Math.max(2, (r.cost / maxCost) * 100)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>

        {/* Reports this cycle */}
        <Panel title="Reports · this cycle">
          <ul className="space-y-3">
            {legend.map((l) => (
              <li key={l.label} className="flex items-center gap-3 text-[14px]">
                <span className={`h-3 w-3 rounded-[3px] ${l.color}`} aria-hidden="true" />
                <span className="flex-1 text-foreground">{l.label}</span>
                <span className="font-mono font-medium text-foreground">{l.count}</span>
              </li>
            ))}
          </ul>
        </Panel>
      </div>

      {/* Recent activity */}
      <Panel title="Recent activity">
        {auditRows.length === 0 ? (
          <p className="text-sm text-muted-foreground">No recent activity.</p>
        ) : (
          <ul className="divide-y divide-border">
            {auditRows.slice(0, 8).map((e) => {
              const clientName = clients.find((c) => c.id === e.client_id)?.name;
              return (
                <li key={e.id} className="flex items-center gap-3 py-2.5 text-[13.5px]">
                  <span className="h-1.5 w-1.5 flex-shrink-0 rounded-full bg-primary" aria-hidden="true" />
                  <span className="flex-1 truncate text-foreground">
                    {humanize(e.action)}
                    {clientName && (
                      <span className="text-[#4a6580] dark:text-[#8095a8]"> · {clientName}</span>
                    )}
                  </span>
                  <span className="flex-shrink-0 font-mono text-[11px] text-[#4a6580] dark:text-[#8095a8]">
                    {TIME_FMT.format(new Date(e.created_at))}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </Panel>
    </div>
  );
}
