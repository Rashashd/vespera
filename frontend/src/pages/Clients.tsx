import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Plus, Settings2, Pause, Play } from "lucide-react";
import {
  useClients,
  useSuspendClient,
  useReactivateClient,
} from "@/api/hooks";
import { useActingClient } from "@/auth/ActingClientContext";
import { CreateClientDialog } from "@/components/admin/CreateClientDialog";
import { Button } from "@/components/ui/button";

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0])
    .join("")
    .toUpperCase();
}

export default function Clients() {
  const { data: clients = [], isLoading, isError } = useClients();
  const { setClientId } = useActingClient();
  const navigate = useNavigate();
  const suspend = useSuspendClient();
  const reactivate = useReactivateClient();
  const [createOpen, setCreateOpen] = useState(false);

  const manage = (id: number) => {
    setClientId(id);
    navigate("/admin");
  };

  const toggleStatus = (id: number, status: string) => {
    const action = status === "active" ? suspend : reactivate;
    action.mutate(id, {
      onSuccess: () =>
        toast.success(
          status === "active" ? "Client suspended." : "Client reactivated.",
        ),
      onError: () => toast.error("Failed to update client status."),
    });
  };

  return (
    <div className="max-w-4xl space-y-5">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          All tenants on the platform.
        </p>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="mr-1 h-4 w-4" />
          New client
        </Button>
      </div>

      {isLoading && <p className="text-muted-foreground text-sm">Loading…</p>}
      {isError && (
        <p className="text-destructive text-sm">Failed to load clients.</p>
      )}
      {!isLoading && !isError && clients.length === 0 && (
        <p className="text-muted-foreground text-sm">
          No clients yet. Create the first one.
        </p>
      )}

      {clients.length > 0 && (
        <div className="overflow-hidden rounded-2xl border bg-card shadow-sm">
          <table className="w-full text-sm">
            <thead className="border-b bg-muted/40 text-left font-mono text-[10.5px] uppercase tracking-[0.12em] text-[#4a6580] dark:text-[#8095a8]">
              <tr>
                <th className="px-5 py-3 font-medium">Client</th>
                <th className="px-5 py-3 font-medium">Status</th>
                <th className="px-5 py-3 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {clients.map((c) => {
                const active = c.status === "active";
                return (
                  <tr key={c.id} className="border-b last:border-0">
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-3">
                        <span className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-primary/12 font-mono text-[11px] font-medium text-primary">
                          {initials(c.name)}
                        </span>
                        <span className="font-medium text-foreground">{c.name}</span>
                      </div>
                    </td>
                    <td className="px-5 py-3.5">
                      <span className="inline-flex items-center gap-1.5 font-mono text-[10.5px] uppercase tracking-[0.1em] text-[#4a6580] dark:text-[#8095a8]">
                        <span
                          className={`h-2 w-2 rounded-full ${active ? "bg-primary" : "bg-[#b07a1e] dark:bg-[#d9a441]"}`}
                          aria-hidden="true"
                        />
                        {active ? "Active" : "Suspended"}
                      </span>
                    </td>
                    <td className="px-5 py-3.5">
                      <div className="flex items-center justify-end gap-2">
                        <Button variant="outline" size="sm" onClick={() => manage(c.id)}>
                          <Settings2 className="mr-1 h-3 w-3" />
                          Manage
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => toggleStatus(c.id, c.status)}
                          disabled={suspend.isPending || reactivate.isPending}
                        >
                          {active ? (
                            <>
                              <Pause className="mr-1 h-3 w-3" />
                              Suspend
                            </>
                          ) : (
                            <>
                              <Play className="mr-1 h-3 w-3" />
                              Reactivate
                            </>
                          )}
                        </Button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <CreateClientDialog open={createOpen} onClose={() => setCreateOpen(false)} />
    </div>
  );
}
