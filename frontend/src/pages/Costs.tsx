import { useQueries } from "@tanstack/react-query";
import { DollarSign, Phone, ArrowDownToLine, ArrowUpFromLine } from "lucide-react";
import { get } from "@/api/client";
import { CostDashboardSchema, type CostDashboard } from "@/api/schemas";
import { useClients } from "@/api/hooks";

function Kpi({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-2xl border bg-card p-5 shadow-sm">
      <div className="flex items-center gap-2 text-[#4a6580] dark:text-[#8095a8]">
        {icon}
        <span className="font-mono text-[10.5px] uppercase tracking-[0.14em]">
          {label}
        </span>
      </div>
      <p className="mt-3 font-display text-[28px] font-semibold leading-none text-foreground">
        {value}
      </p>
    </div>
  );
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

const money = (n: number) =>
  `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export default function Costs() {
  const { data: clients = [], isLoading: clientsLoading } = useClients();

  const costQueries = useQueries({
    queries: clients.map((c) => ({
      queryKey: ["usage", c.id],
      queryFn: () =>
        get<unknown>(`/clients/${c.id}/usage`).then((r) =>
          CostDashboardSchema.parse(r),
        ),
    })),
  });

  const loading = clientsLoading || costQueries.some((q) => q.isLoading);
  const perClient = clients.map((c, i) => ({
    id: c.id,
    name: c.name,
    cost: costQueries[i]?.data ?? null,
  }));

  const totalCost = perClient.reduce(
    (s, c) => s + Number(c.cost?.total_cost_usd ?? 0),
    0,
  );
  const totalCalls = perClient.reduce((s, c) => s + (c.cost?.call_count ?? 0), 0);
  const totalIn = perClient.reduce(
    (s, c) => s + (c.cost?.total_input_tokens ?? 0),
    0,
  );
  const totalOut = perClient.reduce(
    (s, c) => s + (c.cost?.total_output_tokens ?? 0),
    0,
  );

  // Spend by client, ranked high → low.
  const ranked = perClient
    .map((c) => ({ name: c.name, cost: Number(c.cost?.total_cost_usd ?? 0) }))
    .sort((a, b) => b.cost - a.cost);

  // Spend by call site, aggregated across clients.
  const bySite = new Map<string, { cost: number; calls: number }>();
  for (const c of perClient) {
    const sites = (c.cost as CostDashboard | null)?.by_call_site ?? {};
    for (const [site, d] of Object.entries(sites)) {
      const prev = bySite.get(site) ?? { cost: 0, calls: 0 };
      bySite.set(site, {
        cost: prev.cost + Number(d.cost_usd),
        calls: prev.calls + d.calls,
      });
    }
  }
  const siteRows = [...bySite.entries()]
    .map(([site, d]) => ({ site, ...d }))
    .sort((a, b) => b.cost - a.cost);
  const maxSiteCost = Math.max(1, ...siteRows.map((r) => r.cost));

  return (
    <div className="space-y-6">
      <p className="text-sm text-[#4a6580] dark:text-[#8095a8]">
        LLM spend across all clients, current billing window.
      </p>

      {/* Totals */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Kpi icon={<DollarSign className="h-4 w-4" />} label="Total spend" value={money(totalCost)} />
        <Kpi icon={<Phone className="h-4 w-4" />} label="LLM calls" value={totalCalls.toLocaleString()} />
        <Kpi icon={<ArrowDownToLine className="h-4 w-4" />} label="Input tokens" value={totalIn.toLocaleString()} />
        <Kpi icon={<ArrowUpFromLine className="h-4 w-4" />} label="Output tokens" value={totalOut.toLocaleString()} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Spend by client */}
        <Panel
          title="Spend by client"
          aside={
            <span className="font-mono text-[12px] text-[#4a6580] dark:text-[#8095a8]">
              {money(totalCost)} total
            </span>
          }
        >
          {loading && ranked.length === 0 ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : ranked.length === 0 ? (
            <p className="text-sm text-muted-foreground">No clients yet.</p>
          ) : (
            <div className="space-y-4">
              {ranked.map((r) => {
                const pct = totalCost > 0 ? (r.cost / totalCost) * 100 : 0;
                return (
                  <div key={r.name}>
                    <div className="mb-1.5 flex items-center justify-between text-[13px]">
                      <span className="text-foreground">{r.name}</span>
                      <span className="font-mono text-[#4a6580] dark:text-[#8095a8]">
                        {money(r.cost)} · {pct.toFixed(0)}%
                      </span>
                    </div>
                    <div className="h-2 overflow-hidden rounded-full bg-muted">
                      <div
                        className="h-full rounded-full bg-primary"
                        style={{ width: `${Math.max(2, pct)}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </Panel>

        {/* Spend by call site */}
        <Panel title="Spend by call site">
          {siteRows.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No LLM usage recorded yet.
            </p>
          ) : (
            <div className="space-y-4">
              {siteRows.map((r) => (
                <div key={r.site}>
                  <div className="mb-1.5 flex items-center justify-between text-[13px]">
                    <span className="capitalize text-foreground">
                      {r.site.replace(/_/g, " ")}
                    </span>
                    <span className="font-mono text-[#4a6580] dark:text-[#8095a8]">
                      {money(r.cost)} · {r.calls.toLocaleString()} call
                      {r.calls !== 1 ? "s" : ""}
                    </span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full bg-pantera-tealLt"
                      style={{ width: `${Math.max(2, (r.cost / maxSiteCost) * 100)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>

      <p className="text-[12px] text-muted-foreground">
        Month-over-month cost history isn’t available yet — the usage API reports
        the current window only. Per-period trends are a planned backend
        improvement.
      </p>
    </div>
  );
}
