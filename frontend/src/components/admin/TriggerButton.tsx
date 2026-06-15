import { toast } from "sonner";
import { useTriggerIngest } from "@/api/hooks";
import { Button } from "@/components/ui/button";
import { Play } from "lucide-react";

interface Props {
  clientId: number | null;
  watchlistId: number;
  watchlistName: string;
}

export function TriggerButton({ clientId, watchlistId, watchlistName }: Props) {
  const { mutate, isPending } = useTriggerIngest(clientId, watchlistId);

  const handleTrigger = () => {
    mutate(undefined, {
      onSuccess: () =>
        toast.success(`Ingestion queued for "${watchlistName}".`),
      onError: () => toast.error("Failed to trigger ingestion."),
    });
  };

  return (
    <Button
      variant="outline"
      size="sm"
      onClick={handleTrigger}
      disabled={isPending}
      aria-label={`Trigger ingestion for ${watchlistName}`}
    >
      <Play className="h-3 w-3 mr-1" />
      {isPending ? "Queuing…" : "Trigger"}
    </Button>
  );
}
