import { useQueries } from "@tanstack/react-query";
import { Building2, Clock, AlertTriangle, DollarSign } from "lucide-react";
import { get } from "@/api/client";
import {
  OpsDashboardSchema,
  CostDashboardSchema,
  type OpsDashboard,
  type CostDashboard,
} from "@/api/schemas";
import { useClients } from "@/api/hooks";
import { Badge } from "@/components/ui/badge";

interface ClientMetrics {
  ops: OpsDashboard | null;
  cost: CostDashboard | null;
}

function StatCard({
  icon,
  label,
  value,
  hint,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="rounded border bg-card p-4">
      <div className="flex items-center gap-2 text-muted-foreground">
        {icon}
        <span className="text-xs uppercase tracking-wide">{label}</span>
      </div>
      <p className="mt-2 text-2xl font-semibold">{value}</p>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

export default function GlobalOverview() {
  const { data: clients = [], isLoading: clientsLoading } = useClients();

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

  const perClient: (ClientMetrics & { id: number; name: string; status: string })[] =
    clients.map((c, i) => ({
      id: c.id,
      name: c.name,
      status: c.status,
      ops: opsQueries[i]?.data ?? null,
      cost: costQueries[i]?.data ?? null,
    }));

  // Aggregate totals.
  const activeClients = clients.filter((c) => c.status === "active").length;
  const totalPending = perClient.reduce(
    (sum, c) => sum + (c.ops?.queue.pending ?? 0),
    0,
  );
  const totalOverdue = perClient.reduce(
    (sum, c) => sum + (c.ops?.sla.overdue ?? 0),
    0,
  );
  const totalCost = perClient.reduce(
    (sum, c) => sum + Number(c.cost?.total_cost_usd ?? 0),
    0,
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Platform overview</h1>
        <p className="text-sm text-muted-foreground">
          Totals across all clients.
        </p>
      </div>

      {/* Totals */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard
          icon={<Building2 className="h-4 w-4" />}
          label="Active clients"
          value={String(activeClients)}
          hint={`${clients.length} total`}
        />
        <StatCard
          icon={<Clock className="h-4 w-4" />}
          label="Pending review"
          value={String(totalPending)}
          hint="across all queues"
        />
        <StatCard
          icon={<AlertTriangle className="h-4 w-4" />}
          label="SLA overdue"
          value={String(totalOverdue)}
        />
        <StatCard
          icon={<DollarSign className="h-4 w-4" />}
          label="LLM spend"
          value={`$${totalCost.toFixed(2)}`}
          hint="current window"
        />
      </div>

      {/* Per-client table */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold">By client</h2>
        {loading && <p className="text-muted-foreground text-sm">Loading metrics…</p>}
        <div className="overflow-hidden rounded border bg-card">
          <table className="w-full text-sm">
            <thead className="border-b bg-muted/50 text-left text-xs uppercase text-muted-foreground">
              <tr>
                <th className="px-4 py-2 font-medium">Client</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium text-right">Pending</th>
                <th className="px-4 py-2 font-medium text-right">Overdue</th>
                <th className="px-4 py-2 font-medium text-right">SLA met</th>
                <th className="px-4 py-2 font-medium text-right">Spend</th>
              </tr>
            </thead>
            <tbody>
              {perClient.map((c) => (
                <tr key={c.id} className="border-b last:border-0">
                  <td className="px-4 py-3 font-medium">{c.name}</td>
                  <td className="px-4 py-3">
                    <Badge
                      variant={c.status === "active" ? "secondary" : "outline"}
                      className="capitalize"
                    >
                      {c.status}
                    </Badge>
                  </td>
                  <td className="px-4 py-3 text-right">
                    {c.ops?.queue.pending ?? "—"}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {c.ops ? (
                      c.ops.sla.overdue > 0 ? (
                        <span className="text-destructive font-medium">
                          {c.ops.sla.overdue}
                        </span>
                      ) : (
                        0
                      )
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {c.ops ? `${c.ops.sla.met_pct}%` : "—"}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {c.cost ? `$${Number(c.cost.total_cost_usd).toFixed(2)}` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
