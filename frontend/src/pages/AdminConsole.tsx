import { useActingClient } from "@/auth/ActingClientContext";
import { useWatchlists } from "@/api/hooks";
import { TriggerButton } from "@/components/admin/TriggerButton";
import { AuditExportButton } from "@/components/admin/AuditExportButton";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";

export default function AdminConsole() {
  const { clientId, client, clients } = useActingClient();
  const { data: watchlists = [], isLoading, isError } = useWatchlists(clientId);

  if (!clientId) {
    return <p className="text-muted-foreground">Select a client to manage.</p>;
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Admin Console</h1>
        <AuditExportButton />
      </div>

      {/* Client info */}
      {client && (
        <section className="rounded border bg-card p-4 space-y-2">
          <h2 className="text-sm font-semibold">Client</h2>
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">{client.name}</span>
            <Badge variant="outline" className="capitalize">{client.status}</Badge>
          </div>
          {client.custom_severity_keywords && client.custom_severity_keywords.length > 0 && (
            <div>
              <p className="text-xs text-muted-foreground mb-1">Custom severity keywords:</p>
              <div className="flex flex-wrap gap-1">
                {client.custom_severity_keywords.map((kw) => (
                  <Badge key={kw} variant="secondary" className="text-xs">{kw}</Badge>
                ))}
              </div>
            </div>
          )}
        </section>
      )}

      <Separator />

      {/* Watchlists */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold">Watchlists</h2>
        {isLoading && <p className="text-muted-foreground text-sm">Loading…</p>}
        {isError && <p className="text-destructive text-sm">Failed to load watchlists.</p>}
        {!isLoading && !isError && watchlists.length === 0 && (
          <p className="text-muted-foreground text-sm">No watchlists configured.</p>
        )}
        <ol className="space-y-2">
          {watchlists.map((w) => (
            <li key={w.id} className="rounded border bg-card p-3 flex items-center justify-between gap-3">
              <div>
                <p className="text-sm font-medium">{w.name}</p>
                <Badge variant="muted" className="text-xs capitalize">{w.status}</Badge>
              </div>
              <TriggerButton
                clientId={clientId}
                watchlistId={w.id}
                watchlistName={w.name}
              />
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
