import { useState } from "react";
import { toast } from "sonner";
import { useCreateClient } from "@/api/hooks";
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

const THRESHOLDS = [
  { value: "non-serious", label: "Non-serious" },
  { value: "serious", label: "Serious" },
  { value: "life-threatening", label: "Life-threatening" },
];

export function CreateClientDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { mutate, isPending } = useCreateClient();
  const [name, setName] = useState("");
  const [emailRegular, setEmailRegular] = useState("");
  const [emailUrgent, setEmailUrgent] = useState("");
  const [threshold, setThreshold] = useState("life-threatening");

  const reset = () => {
    setName("");
    setEmailRegular("");
    setEmailUrgent("");
    setThreshold("life-threatening");
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    mutate(
      {
        name: name.trim(),
        report_email_regular: emailRegular.trim() || null,
        report_email_urgent: emailUrgent.trim() || null,
        urgent_severity_threshold: threshold,
      },
      {
        onSuccess: (client) => {
          toast.success(`Client "${client.name}" created.`);
          reset();
          onClose();
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 409) {
            toast.error("A client with that name already exists.");
          } else if (err instanceof ApiError && err.status === 400) {
            toast.error("Invalid email address.");
          } else {
            toast.error("Failed to create client.");
          }
        },
      },
    );
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Create client"
      description="Add a new tenant. Watchlists and users are configured afterward."
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="client-name">Name</Label>
          <Input
            id="client-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Acme Pharma"
            required
            autoFocus
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="email-regular">Regular report email (optional)</Label>
          <Input
            id="email-regular"
            type="email"
            value={emailRegular}
            onChange={(e) => setEmailRegular(e.target.value)}
            placeholder="pv@acme.example"
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="email-urgent">Urgent report email (optional)</Label>
          <Input
            id="email-urgent"
            type="email"
            value={emailUrgent}
            onChange={(e) => setEmailUrgent(e.target.value)}
            placeholder="urgent@acme.example"
          />
        </div>

        <div className="space-y-2">
          <Label>Urgent severity threshold</Label>
          <Select value={threshold} onValueChange={setThreshold}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {THRESHOLDS.map((t) => (
                <SelectItem key={t.value} value={t.value}>
                  {t.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={isPending || !name.trim()}>
            {isPending ? "Creating…" : "Create client"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
