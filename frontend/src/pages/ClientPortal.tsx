import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { usePortalReports, useWatchlists } from "@/api/hooks";
import { useAuth } from "@/auth/AuthContext";
import { SeverityBadge } from "@/components/SeverityBadge";
import type { FindingBucket, PortalReportSummary } from "@/api/schemas";

const SEV_RANK: Record<string, number> = { emergency: 4, urgent: 3, minor: 2, positive: 1 };
const SEV_ORDER: FindingBucket[] = ["emergency", "urgent", "minor", "positive"];

function topSeverity(reports: PortalReportSummary[]): FindingBucket | null {
  let best: FindingBucket | null = null;
  for (const r of reports) {
    if (r.severity && (best === null || SEV_RANK[r.severity] > SEV_RANK[best])) {
      best = r.severity;
    }
  }
  return best;
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-2xl border bg-card p-4 shadow-sm">
      <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-[#4a6580] dark:text-[#8095a8]">
        {label}
      </p>
      <p className="mt-1.5 font-display text-[26px] font-semibold leading-none text-foreground">
        {value}
      </p>
    </div>
  );
}

function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <h2 className="font-mono text-[11px] uppercase tracking-[0.16em] text-[#4a6580] dark:text-[#8095a8]">
      {children}
    </h2>
  );
}

export default function ClientPortal() {
  const { user } = useAuth();
  const clientId = user?.client_id ?? null;
  const navigate = useNavigate();
  const { data: watchlists = [], isLoading: wlLoading, isError: wlError } =
    useWatchlists(clientId);
  const { data: reports = [], isLoading: rLoading, isError: rError } =
    usePortalReports(clientId);

  if (!clientId) {
    return <p className="text-muted-foreground">No client associated with your account.</p>;
  }
  if (wlLoading || rLoading) {
    return <p className="text-muted-foreground">Loading…</p>;
  }
  if (wlError || rError) {
    return <p className="text-destructive">Failed to load portal data.</p>;
  }

  const delivered = reports.filter((r) => r.status === "delivered").length;
  const awaiting = reports.filter((r) => r.status === "approved" || r.status === "sent").length;
  const sevCounts: Record<string, number> = { emergency: 0, urgent: 0, minor: 0, positive: 0 };
  for (const r of reports) {
    if (r.severity && r.severity in sevCounts) sevCounts[r.severity] += 1;
  }
  const totalSev = SEV_ORDER.reduce((s, b) => s + sevCounts[b], 0);

  return (
    <div className="space-y-6">
      {/* Dashboard */}
      <section className="space-y-3">
        <SectionLabel>Overview</SectionLabel>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Reports" value={reports.length} />
          <Stat label="Delivered" value={delivered} />
          <Stat label="Awaiting" value={awaiting} />
          <Stat label="Watchlists" value={watchlists.length} />
        </div>
        {totalSev > 0 && (
          <div className="flex flex-wrap items-center gap-3 rounded-2xl border bg-card p-4 shadow-sm">
            <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-[#4a6580] dark:text-[#8095a8]">
              By severity
            </span>
            {SEV_ORDER.filter((b) => sevCounts[b] > 0).map((b) => (
              <span key={b} className="inline-flex items-center gap-1.5">
                <SeverityBadge bucket={b} />
                <span className="text-sm font-medium text-foreground">{sevCounts[b]}</span>
              </span>
            ))}
          </div>
        )}
      </section>

      {/* Watchlists */}
      <section className="space-y-3">
        <SectionLabel>Watchlists</SectionLabel>
        {watchlists.length === 0 ? (
          <div className="rounded-2xl border bg-card p-10 text-center text-muted-foreground shadow-sm">
            No watchlists configured for your account.
          </div>
        ) : (
          <ol className="space-y-3">
            {watchlists.map((w) => {
              const wlReports = reports.filter((r) => r.watchlist_id === w.id);
              const sev = topSeverity(wlReports);
              const keywords = w.items.map((it) => it.value).filter(Boolean);
              return (
                <li key={w.id}>
                  <button
                    type="button"
                    className={`w-full rounded-xl border bg-card p-4 text-left shadow-sm transition-colors hover:border-primary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                      w.is_active ? "" : "opacity-60"
                    }`}
                    onClick={() => navigate(`/portal/watchlists/${w.id}`)}
                    aria-label={`View reports for watchlist ${w.name}`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          {sev && <SeverityBadge bucket={sev} />}
                          <p className="font-display text-[15px] font-semibold text-foreground">
                            {w.name}
                          </p>
                        </div>
                        <p className="mt-0.5 text-[12.5px] text-muted-foreground">
                          {wlReports.length} report{wlReports.length !== 1 ? "s" : ""} ·{" "}
                          <span className="capitalize">{w.cadence}</span> cadence
                        </p>
                      </div>
                      <span className="inline-flex flex-shrink-0 items-center gap-1.5 font-mono text-[10.5px] uppercase tracking-[0.1em] text-[#4a6580] dark:text-[#8095a8]">
                        <span
                          className={`h-2 w-2 rounded-full ${w.is_active ? "bg-primary" : "bg-muted-foreground"}`}
                          aria-hidden="true"
                        />
                        {w.is_active ? "Active" : "Inactive"}
                      </span>
                    </div>
                    {keywords.length > 0 && (
                      <div className="mt-3 flex flex-wrap gap-1.5">
                        {keywords.slice(0, 8).map((k, i) => (
                          <span
                            key={i}
                            className="rounded-md bg-secondary px-2 py-0.5 font-mono text-[10.5px] text-secondary-foreground"
                          >
                            {k}
                          </span>
                        ))}
                        {keywords.length > 8 && (
                          <span className="px-1 py-0.5 text-[10.5px] text-muted-foreground">
                            +{keywords.length - 8} more
                          </span>
                        )}
                      </div>
                    )}
                  </button>
                </li>
              );
            })}
          </ol>
        )}
      </section>
    </div>
  );
}
