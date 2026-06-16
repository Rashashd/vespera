import { useState } from "react";
import { toast } from "sonner";
import { Plus, Trash2, Save } from "lucide-react";
import {
  useUpdateWatchlist,
  useAddWatchlistItem,
  useRemoveWatchlistItem,
} from "@/api/hooks";
import type { Watchlist } from "@/api/schemas";
import { TriggerButton } from "./TriggerButton";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  CADENCE_OPTIONS,
  SEVERITY_OPTIONS,
  POLICY_OPTIONS,
  ITEM_TYPE_OPTIONS,
} from "./watchlist-constants";

const BUDGET_VARIANT: Record<string, "secondary" | "outline" | "destructive"> = {
  ok: "secondary",
  warning: "outline",
  exceeded: "destructive",
  none: "outline",
};

export function WatchlistEditor({
  clientId,
  watchlist,
}: {
  clientId: number | null;
  watchlist: Watchlist;
}) {
  const update = useUpdateWatchlist(clientId);
  const addItem = useAddWatchlistItem(clientId);
  const removeItem = useRemoveWatchlistItem(clientId);

  const [cadence, setCadence] = useState(watchlist.cadence);
  const [severity, setSeverity] = useState(watchlist.severity_threshold);
  const [policy, setPolicy] = useState(watchlist.budget_exceeded_policy);
  const [budget, setBudget] = useState(watchlist.budget_amount ?? "");
  const [newType, setNewType] = useState("drug");
  const [newValue, setNewValue] = useState("");

  const dirty =
    cadence !== watchlist.cadence ||
    severity !== watchlist.severity_threshold ||
    policy !== watchlist.budget_exceeded_policy ||
    (budget || "") !== (watchlist.budget_amount ?? "");

  const saveSettings = () => {
    update.mutate(
      {
        watchlistId: watchlist.id,
        body: {
          cadence,
          severity_threshold: severity,
          budget_exceeded_policy: policy,
          budget_amount: String(budget).trim() ? String(budget).trim() : null,
        },
      },
      {
        onSuccess: () => toast.success("Watchlist settings saved."),
        onError: () => toast.error("Failed to save settings."),
      },
    );
  };

  const handleAddItem = () => {
    const value = newValue.trim();
    if (!value) return;
    addItem.mutate(
      { watchlistId: watchlist.id, item_type: newType, value },
      {
        onSuccess: () => {
          setNewValue("");
          toast.success(`Added "${value}".`);
        },
        onError: () => toast.error("Failed to add item."),
      },
    );
  };

  const handleRemoveItem = (itemId: number, value: string) => {
    removeItem.mutate(
      { watchlistId: watchlist.id, itemId },
      {
        onSuccess: () => toast.success(`Removed "${value}".`),
        onError: () => toast.error("Failed to remove item."),
      },
    );
  };

  return (
    <div className="rounded border bg-card p-4 space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <p className="text-sm font-medium">{watchlist.name}</p>
          {!watchlist.is_active && (
            <Badge variant="outline" className="text-xs">
              inactive
            </Badge>
          )}
          <Badge
            variant={BUDGET_VARIANT[watchlist.budget_status] ?? "outline"}
            className="text-xs capitalize"
          >
            budget: {watchlist.budget_status}
          </Badge>
        </div>
        <TriggerButton
          clientId={clientId}
          watchlistId={watchlist.id}
          watchlistName={watchlist.name}
        />
      </div>

      {/* Settings */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <div className="space-y-1">
          <Label className="text-xs">Cadence</Label>
          <Select value={cadence} onValueChange={setCadence}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {CADENCE_OPTIONS.map((o) => (
                <SelectItem key={o.value} value={o.value}>
                  {o.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Severity</Label>
          <Select value={severity} onValueChange={setSeverity}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SEVERITY_OPTIONS.map((o) => (
                <SelectItem key={o.value} value={o.value}>
                  {o.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Budget (USD)</Label>
          <Input
            type="number"
            min="0"
            step="0.01"
            value={budget}
            onChange={(e) => setBudget(e.target.value)}
            placeholder="none"
          />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Over-budget</Label>
          <Select value={policy} onValueChange={setPolicy}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {POLICY_OPTIONS.map((o) => (
                <SelectItem key={o.value} value={o.value}>
                  {o.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {dirty && (
        <div className="flex justify-end">
          <Button size="sm" onClick={saveSettings} disabled={update.isPending}>
            <Save className="h-3 w-3 mr-1" />
            {update.isPending ? "Saving…" : "Save settings"}
          </Button>
        </div>
      )}

      {/* Items */}
      <div className="space-y-2">
        <Label className="text-xs">Monitored items ({watchlist.items.length})</Label>
        <div className="flex flex-wrap gap-1">
          {watchlist.items.length === 0 && (
            <span className="text-xs text-muted-foreground">No items.</span>
          )}
          {watchlist.items.map((it) => (
            <Badge
              key={it.id}
              variant="secondary"
              className="text-xs flex items-center gap-1"
            >
              <span className="opacity-60">{it.item_type}:</span>
              {it.value}
              <button
                type="button"
                onClick={() => handleRemoveItem(it.id, it.value)}
                className="ml-0.5 hover:text-destructive"
                aria-label={`Remove ${it.value}`}
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </Badge>
          ))}
        </div>
        <div className="flex items-center gap-2 pt-1">
          <div className="w-28 shrink-0">
            <Select value={newType} onValueChange={setNewType}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {ITEM_TYPE_OPTIONS.map((o) => (
                  <SelectItem key={o.value} value={o.value}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Input
            value={newValue}
            onChange={(e) => setNewValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                handleAddItem();
              }
            }}
            placeholder="Add drug or keyword…"
          />
          <Button
            variant="outline"
            size="sm"
            onClick={handleAddItem}
            disabled={addItem.isPending || !newValue.trim()}
          >
            <Plus className="h-3 w-3 mr-1" />
            Add
          </Button>
        </div>
      </div>
    </div>
  );
}
