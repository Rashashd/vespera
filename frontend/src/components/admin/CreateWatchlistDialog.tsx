import { useState } from "react";
import { toast } from "sonner";
import { Plus, Trash2 } from "lucide-react";
import { useCreateWatchlist } from "@/api/hooks";
import { ApiError } from "@/api/client";
import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
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

interface DraftItem {
  item_type: string;
  value: string;
}

export function CreateWatchlistDialog({
  clientId,
  open,
  onClose,
}: {
  clientId: number | null;
  open: boolean;
  onClose: () => void;
}) {
  const { mutate, isPending } = useCreateWatchlist(clientId);
  const [name, setName] = useState("");
  const [cadence, setCadence] = useState("weekly");
  const [severity, setSeverity] = useState("serious");
  const [policy, setPolicy] = useState("continue");
  const [budget, setBudget] = useState("");
  const [items, setItems] = useState<DraftItem[]>([
    { item_type: "drug", value: "" },
  ]);

  const reset = () => {
    setName("");
    setCadence("weekly");
    setSeverity("serious");
    setPolicy("continue");
    setBudget("");
    setItems([{ item_type: "drug", value: "" }]);
  };

  const updateItem = (i: number, patch: Partial<DraftItem>) =>
    setItems((prev) => prev.map((it, idx) => (idx === i ? { ...it, ...patch } : it)));
  const addItem = () =>
    setItems((prev) => [...prev, { item_type: "drug", value: "" }]);
  const removeItem = (i: number) =>
    setItems((prev) => prev.filter((_, idx) => idx !== i));

  const validItems = items
    .map((it) => ({ item_type: it.item_type, value: it.value.trim() }))
    .filter((it) => it.value);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (validItems.length === 0) {
      toast.error("Add at least one drug or keyword.");
      return;
    }
    mutate(
      {
        name: name.trim(),
        cadence,
        severity_threshold: severity,
        budget_amount: budget.trim() ? budget.trim() : null,
        budget_exceeded_policy: policy,
        items: validItems,
      },
      {
        onSuccess: (wl) => {
          toast.success(`Watchlist "${wl.name}" created.`);
          reset();
          onClose();
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 409) {
            toast.error("A watchlist with that name already exists.");
          } else {
            toast.error("Failed to create watchlist.");
          }
        },
      },
    );
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Create watchlist"
      description="A monitoring group with its own cadence, severity threshold, and budget."
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="wl-name">Name</Label>
          <Input
            id="wl-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Oncology portfolio"
            required
            autoFocus
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-2">
            <Label>Cadence</Label>
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
          <div className="space-y-2">
            <Label>Severity threshold</Label>
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
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-2">
            <Label htmlFor="wl-budget">Budget (USD, optional)</Label>
            <Input
              id="wl-budget"
              type="number"
              min="0"
              step="0.01"
              value={budget}
              onChange={(e) => setBudget(e.target.value)}
              placeholder="e.g. 50.00"
            />
          </div>
          <div className="space-y-2">
            <Label>Over-budget policy</Label>
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

        <div className="space-y-2">
          <Label>Monitored items</Label>
          <div className="space-y-2">
            {items.map((it, i) => (
              <div key={i} className="flex items-center gap-2">
                <div className="w-28 shrink-0">
                  <Select
                    value={it.item_type}
                    onValueChange={(v) => updateItem(i, { item_type: v })}
                  >
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
                  value={it.value}
                  onChange={(e) => updateItem(i, { value: e.target.value })}
                  placeholder="aspirin"
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={() => removeItem(i)}
                  disabled={items.length === 1}
                  aria-label="Remove item"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            ))}
          </div>
          <Button type="button" variant="outline" size="sm" onClick={addItem}>
            <Plus className="h-3 w-3 mr-1" />
            Add item
          </Button>
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={isPending || !name.trim()}>
            {isPending ? "Creating…" : "Create watchlist"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
