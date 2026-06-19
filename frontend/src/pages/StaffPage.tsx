import { useState } from "react";
import { useStaff, useCreateStaff, useUpdateStaff } from "@/api/hooks";
import { ApiError } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const ROLES = ["reviewer", "admin", "manager"];

export default function StaffPage() {
  const { data: staff = [], isLoading, isError } = useStaff();
  const createStaff = useCreateStaff();
  const updateStaff = useUpdateStaff();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("reviewer");
  const [error, setError] = useState<string | null>(null);

  function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    createStaff.mutate(
      { email, password, role },
      {
        onSuccess: () => {
          setEmail("");
          setPassword("");
          setRole("reviewer");
        },
        onError: (err) =>
          setError(err instanceof ApiError ? err.detail : "Failed to create staff user"),
      },
    );
  }

  return (
    <div className="max-w-3xl space-y-6">
      <p className="text-sm text-muted-foreground">
        Manage internal staff accounts (reviewer / admin / manager). Manager-only.
      </p>

      <form onSubmit={handleCreate} className="space-y-3 rounded-2xl border bg-card p-5 shadow-sm">
        <h2 className="font-display text-[15px] font-semibold text-foreground">Create staff user</h2>
        <div className="grid sm:grid-cols-3 gap-3">
          <div className="space-y-1">
            <Label htmlFor="staff-email">Email</Label>
            <Input
              id="staff-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="staff-password">Initial password</Label>
            <Input
              id="staff-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="staff-role">Role</Label>
            <select
              id="staff-role"
              className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm capitalize"
              value={role}
              onChange={(e) => setRole(e.target.value)}
            >
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </div>
        </div>
        {error && <p className="text-sm text-destructive">{error}</p>}
        <Button type="submit" size="sm" disabled={createStaff.isPending}>
          {createStaff.isPending ? "Creating…" : "Create"}
        </Button>
        <p className="text-xs text-muted-foreground">
          Communicate the initial password out-of-band; the user can change it after signing in.
        </p>
      </form>

      <section className="space-y-3">
        <h2 className="font-display text-[15px] font-semibold text-foreground">Existing staff</h2>
        {isLoading && <p className="text-muted-foreground text-sm">Loading…</p>}
        {isError && <p className="text-destructive text-sm">Failed to load staff.</p>}
        <ul className="space-y-2">
          {staff.map((u) => (
            <li
              key={u.id}
              className={`flex items-center justify-between gap-3 rounded-xl border bg-card p-3.5 shadow-sm ${u.is_active ? "" : "opacity-60"}`}
            >
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm font-medium">{u.email}</span>
                <Badge variant="outline" className="capitalize text-xs">
                  {u.role}
                </Badge>
                {!u.is_active && (
                  <Badge variant="muted" className="text-xs">
                    inactive
                  </Badge>
                )}
              </div>
              <Button
                variant="outline"
                size="sm"
                disabled={updateStaff.isPending}
                onClick={() =>
                  updateStaff.mutate({ userId: u.id, body: { is_active: !u.is_active } })
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
