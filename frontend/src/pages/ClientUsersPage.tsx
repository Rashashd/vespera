import { useState } from "react";
import {
  useClientUsers,
  useCreateClientUser,
  useUpdateClientUser,
  useWatchlists,
} from "@/api/hooks";
import { ApiError } from "@/api/client";
import { useActingClient } from "@/auth/ActingClientContext";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const SEVERITIES = ["", "non-serious", "serious", "life-threatening"];

export default function ClientUsersPage() {
  const { clientId, client } = useActingClient();
  const { data: users = [], isLoading, isError } = useClientUsers(clientId);
  const { data: watchlists = [] } = useWatchlists(clientId);
  const createUser = useCreateClientUser(clientId);
  const updateUser = useUpdateClientUser(clientId);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [scope, setScope] = useState("full");
  const [minSeverity, setMinSeverity] = useState("");
  const [watchlistIds, setWatchlistIds] = useState<number[]>([]);
  const [error, setError] = useState<string | null>(null);

  if (!clientId) {
    return <p className="text-muted-foreground">Select a client to manage its users.</p>;
  }

  function toggleWatchlist(id: number) {
    setWatchlistIds((ids) => (ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]));
  }

  function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    createUser.mutate(
      {
        email,
        password,
        client_scope: scope,
        min_severity: minSeverity || null,
        watchlist_ids: scope === "scoped" ? watchlistIds : [],
      },
      {
        onSuccess: () => {
          setEmail("");
          setPassword("");
          setScope("full");
          setMinSeverity("");
          setWatchlistIds([]);
        },
        onError: (err) =>
          setError(err instanceof ApiError ? err.detail : "Failed to create client user"),
      },
    );
  }

  return (
    <div className="max-w-3xl space-y-6">
      <p className="text-sm text-muted-foreground">
        Manage portal users for {client ? client.name : "the acting client"}. Manager / admin only.
      </p>

      <form onSubmit={handleCreate} className="space-y-3 rounded-2xl border bg-card p-5 shadow-sm">
        <h2 className="font-display text-[15px] font-semibold text-foreground">Create client user</h2>
        <div className="grid sm:grid-cols-2 gap-3">
          <div className="space-y-1">
            <Label htmlFor="cu-email">Email</Label>
            <Input
              id="cu-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="cu-password">Initial password</Label>
            <Input
              id="cu-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="cu-scope">Scope</Label>
            <select
              id="cu-scope"
              className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm capitalize"
              value={scope}
              onChange={(e) => setScope(e.target.value)}
            >
              <option value="full">full</option>
              <option value="scoped">scoped</option>
            </select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="cu-severity">Min severity (optional)</Label>
            <select
              id="cu-severity"
              className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm"
              value={minSeverity}
              onChange={(e) => setMinSeverity(e.target.value)}
            >
              {SEVERITIES.map((s) => (
                <option key={s} value={s}>
                  {s || "— none —"}
                </option>
              ))}
            </select>
          </div>
        </div>
        {scope === "scoped" && (
          <div className="space-y-1">
            <Label>Visible watchlists</Label>
            <div className="flex flex-wrap gap-3 rounded border p-2">
              {watchlists.length === 0 && (
                <span className="text-xs text-muted-foreground">No watchlists for this client.</span>
              )}
              {watchlists.map((w) => (
                <label key={w.id} className="flex items-center gap-1.5 text-sm">
                  <input
                    type="checkbox"
                    checked={watchlistIds.includes(w.id)}
                    onChange={() => toggleWatchlist(w.id)}
                  />
                  {w.name}
                </label>
              ))}
            </div>
          </div>
        )}
        {error && <p className="text-sm text-destructive">{error}</p>}
        <Button type="submit" size="sm" disabled={createUser.isPending}>
          {createUser.isPending ? "Creating…" : "Create"}
        </Button>
        <p className="text-xs text-muted-foreground">
          Communicate the initial password out-of-band; the user can change it after signing in.
        </p>
      </form>

      <section className="space-y-3">
        <h2 className="font-display text-[15px] font-semibold text-foreground">Existing users</h2>
        {isLoading && <p className="text-muted-foreground text-sm">Loading…</p>}
        {isError && <p className="text-destructive text-sm">Failed to load client users.</p>}
        <ul className="space-y-2">
          {users.map((u) => (
            <li
              key={u.id}
              className={`flex items-center justify-between gap-3 rounded-xl border bg-card p-3.5 shadow-sm ${u.is_active ? "" : "opacity-60"}`}
            >
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm font-medium">{u.email}</span>
                <Badge variant="outline" className="capitalize text-xs">
                  {u.client_scope ?? "full"}
                </Badge>
                {u.client_scope === "scoped" && (
                  <span className="text-xs text-muted-foreground">
                    {u.watchlist_ids.length} watchlist{u.watchlist_ids.length !== 1 ? "s" : ""}
                  </span>
                )}
                {u.min_severity && (
                  <Badge variant="muted" className="text-xs">
                    ≥ {u.min_severity}
                  </Badge>
                )}
                {!u.is_active && (
                  <Badge variant="muted" className="text-xs">
                    inactive
                  </Badge>
                )}
              </div>
              <Button
                variant="outline"
                size="sm"
                disabled={updateUser.isPending}
                onClick={() =>
                  updateUser.mutate({ userId: u.id, body: { is_active: !u.is_active } })
                }
              >
                {u.is_active ? "Deactivate" : "Reactivate"}
              </Button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
