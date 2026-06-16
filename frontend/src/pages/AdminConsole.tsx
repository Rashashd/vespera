import { useState } from "react";
import { Plus } from "lucide-react";
import { useActingClient } from "@/auth/ActingClientContext";
import { useWatchlists } from "@/api/hooks";
import { AuditExportButton } from "@/components/admin/AuditExportButton";
import { CreateWatchlistDialog } from "@/components/admin/CreateWatchlistDialog";
import { WatchlistEditor } from "@/components/admin/WatchlistEditor";
import { SeverityKeywordsEditor } from "@/components/admin/SeverityKeywordsEditor";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";

export default function AdminConsole() {
  const { clientId, client } = useActingClient();
  const { data: watchlists = [], isLoading, isError } = useWatchlists(clientId);
  const [createOpen, setCreateOpen] = useState(false);

  if (!clientId) {
    return <p className="text-muted-foreground">Select a client to manage.</p>;
  }

  return (
    <div className="space-y-6 max-w-4xl">
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
            <Badge variant="outline" className="capitalize">
              {client.status}
            </Badge>
          </div>
        </section>
      )}

      {/* Severity escalation keywords */}
      <SeverityKeywordsEditor
        clientId={clientId}
        keywords={client?.custom_severity_keywords ?? []}
      />

      <Separator />

      {/* Watchlists */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold">Watchlists</h2>
          <Button size="sm" onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4 mr-1" />
            New watchlist
          </Button>
        </div>
        {isLoading && <p className="text-muted-foreground text-sm">Loading…</p>}
        {isError && (
          <p className="text-destructive text-sm">Failed to load watchlists.</p>
        )}
        {!isLoading && !isError && watchlists.length === 0 && (
          <p className="text-muted-foreground text-sm">No watchlists configured.</p>
        )}
        <div className="space-y-3">
          {watchlists.map((w) => (
            <WatchlistEditor key={w.id} clientId={clientId} watchlist={w} />
          ))}
        </div>
      </section>

      <CreateWatchlistDialog
        clientId={clientId}
        open={createOpen}
        onClose={() => setCreateOpen(false)}
      />
    </div>
  );
}
