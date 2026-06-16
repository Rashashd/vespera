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
import { Badge } from "@/components/ui/badge";

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
    <div className="space-y-6 max-w-4xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Clients</h1>
          <p className="text-sm text-muted-foreground">
            All tenants on the platform.
          </p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="h-4 w-4 mr-1" />
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
        <div className="overflow-hidden rounded border bg-card">
          <table className="w-full text-sm">
            <thead className="border-b bg-muted/50 text-left text-xs uppercase text-muted-foreground">
              <tr>
                <th className="px-4 py-2 font-medium">ID</th>
                <th className="px-4 py-2 font-medium">Name</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {clients.map((c) => (
                <tr key={c.id} className="border-b last:border-0">
                  <td className="px-4 py-3 text-muted-foreground">{c.id}</td>
                  <td className="px-4 py-3 font-medium">{c.name}</td>
                  <td className="px-4 py-3">
                    <Badge
                      variant={c.status === "active" ? "secondary" : "outline"}
                      className="capitalize"
                    >
                      {c.status}
                    </Badge>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => manage(c.id)}
                      >
                        <Settings2 className="h-3 w-3 mr-1" />
                        Manage
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => toggleStatus(c.id, c.status)}
                        disabled={suspend.isPending || reactivate.isPending}
                      >
                        {c.status === "active" ? (
                          <>
                            <Pause className="h-3 w-3 mr-1" />
                            Suspend
                          </>
                        ) : (
                          <>
                            <Play className="h-3 w-3 mr-1" />
                            Reactivate
                          </>
                        )}
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <CreateClientDialog open={createOpen} onClose={() => setCreateOpen(false)} />
    </div>
  );
}
