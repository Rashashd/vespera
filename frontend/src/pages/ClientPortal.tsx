import { useNavigate } from "react-router-dom";
import { usePortalReports } from "@/api/hooks";
import { useWatchlists } from "@/api/hooks";
import { useAuth } from "@/auth/AuthContext";

export default function ClientPortal() {
  const { user } = useAuth();
  const clientId = user?.client_id ?? null;
  const navigate = useNavigate();
  const { data: watchlists = [], isLoading: wlLoading, isError: wlError } = useWatchlists(clientId);
  const { data: reports = [], isLoading: rLoading, isError: rError } = usePortalReports(clientId);

  if (!clientId) {
    return <p className="text-muted-foreground">No client associated with your account.</p>;
  }

  const isLoading = wlLoading || rLoading;
  const isError = wlError || rError;

  if (isLoading) {
    return <p className="text-muted-foreground">Loading…</p>;
  }

  if (isError) {
    return <p className="text-destructive">Failed to load portal data.</p>;
  }

  if (watchlists.length === 0) {
    return (
      <div className="rounded-2xl border bg-card p-10 text-center text-muted-foreground shadow-sm">
        No watchlists configured for your account.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Your monitored watchlists and their delivered reports.
      </p>
      <ol className="space-y-3">
        {watchlists.map((w) => {
          const wlReports = reports.filter((r) => r.watchlist_id === w.id);
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
                    <p className="font-display text-[15px] font-semibold text-foreground">
                      {w.name}
                    </p>
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
    </div>
  );
}
