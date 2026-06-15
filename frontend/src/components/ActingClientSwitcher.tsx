import { useActingClient } from "@/auth/ActingClientContext";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export function ActingClientSwitcher() {
  const { clientId, clients, setClientId } = useActingClient();

  if (clients.length === 0) return null;

  return (
    <Select
      value={clientId ? String(clientId) : ""}
      onValueChange={(v) => setClientId(parseInt(v, 10))}
    >
      <SelectTrigger className="h-8 w-48 text-sm" aria-label="Select acting client">
        <SelectValue placeholder="Select client…" />
      </SelectTrigger>
      <SelectContent>
        {clients.map((c) => (
          <SelectItem key={c.id} value={String(c.id)}>
            {c.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
