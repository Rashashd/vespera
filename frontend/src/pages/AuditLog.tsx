import { useState } from "react";
import { useAuditLog } from "@/api/hooks";
import { useActingClient } from "@/auth/ActingClientContext";
import type { AuditEntry } from "@/api/schemas";
import { AuditExportButton } from "@/components/admin/AuditExportButton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const CATEGORIES = [
  { value: "all", label: "All activity" },
  { value: "reports", label: "Reports" },
  { value: "findings", label: "Findings" },
  { value: "clients", label: "Clients" },
  { value: "jobs", label: "Failures" },
];

// Humanize a domain-event class name: "ReportApproved" → "Report approved".
function humanize(eventType: string): string {
  const spaced = eventType.replace(/([a-z])([A-Z])/g, "$1 $2");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1).toLowerCase();
}

// Outcome colour for report/job events.
function toneFor(eventType: string): "secondary" | "destructive" | "outline" {
  if (/Approved$/.test(eventType)) return "secondary";
  if (/Rejected|Discarded|DeadLettered|Alert|Failed/.test(eventType)) return "destructive";
  return "outline";
}

function actorLabel(e: AuditEntry): string {
  if (e.actor_type === "system" || e.actor_id === 0) return "system";
  if (e.actor_user_id) return `user #${e.actor_user_id}`;
  return `${e.actor_type} #${e.actor_id}`;
}

export default function AuditLog() {
  const [category, setCategory] = useState("all");
  const [scoped, setScoped] = useState(false);
  const { clientId, client, clients } = useActingClient();
  const { data: entries = [], isLoading, isError } = useAuditLog({
    category,
    clientId: scoped ? clientId : undefined,
  });

  const clientName = (id: number | null | undefined) =>
    id == null ? "—" : clients.find((c) => c.id === id)?.name ?? `Client ${id}`;

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Audit log</h1>
          <p className="text-sm text-muted-foreground">
            Append-only record of every change and report outcome across all clients.
          </p>
        </div>
        <AuditExportButton />
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        {CATEGORIES.map((c) => (
          <Button
            key={c.value}
            variant={category === c.value ? "default" : "outline"}
            size="sm"
            onClick={() => setCategory(c.value)}
          >
            {c.label}
          </Button>
        ))}
        <div className="ml-auto">
          <Button
            variant={scoped ? "default" : "outline"}
            size="sm"
            onClick={() => setScoped((s) => !s)}
            disabled={!clientId}
            title={clientId ? undefined : "Select an acting client to scope"}
          >
            {scoped ? `Scoped: ${client?.name ?? "client"}` : "All clients"}
          </Button>
        </div>
      </div>

      {isLoading && <p className="text-muted-foreground text-sm">Loading…</p>}
      {isError && (
        <p className="text-destructive text-sm">Failed to load the audit log.</p>
      )}
      {!isLoading && !isError && entries.length === 0 && (
        <p className="text-muted-foreground text-sm">No matching activity.</p>
      )}

      {entries.length > 0 && (
        <div className="overflow-hidden rounded border bg-card">
          <table className="w-full text-sm">
            <thead className="border-b bg-muted/50 text-left text-xs uppercase text-muted-foreground">
              <tr>
                <th className="px-4 py-2 font-medium">When</th>
                <th className="px-4 py-2 font-medium">Event</th>
                <th className="px-4 py-2 font-medium">Target</th>
                <th className="px-4 py-2 font-medium">Client</th>
                <th className="px-4 py-2 font-medium">Actor</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.id} className="border-b last:border-0 align-top">
                  <td className="px-4 py-3 whitespace-nowrap text-muted-foreground">
                    {new Date(e.created_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant={toneFor(e.event_type)} className="text-xs">
                      {humanize(e.event_type)}
                    </Badge>
                  </td>
                  <td className={cn("px-4 py-3 font-mono text-xs")}>{e.target}</td>
                  <td className="px-4 py-3">{clientName(e.client_id)}</td>
                  <td className="px-4 py-3 text-muted-foreground">{actorLabel(e)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {entries.length >= 100 && (
        <p className="text-xs text-muted-foreground">
          Showing the most recent 100 entries.
        </p>
      )}
    </div>
  );
}
