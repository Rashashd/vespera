import { toast } from "sonner";
import { useDropFinding, useDiscardFinding } from "@/api/hooks";
import { cn } from "@/lib/utils";
import { Button } from "./ui/button";
import type { ReportFindingDetail } from "@/api/schemas";

const BUCKET_COLOR: Record<string, string> = {
  emergency: "text-red-600 dark:text-red-400",
  urgent: "text-amber-600 dark:text-amber-400",
  minor: "text-muted-foreground",
  positive: "text-emerald-600 dark:text-emerald-500",
};

interface Props {
  finding: ReportFindingDetail;
  selected: boolean;
  onSelect: () => void;
  clientId: number | null;
  reportId: number;
  readOnly: boolean;
}

export function FindingRow({ finding, selected, onSelect, clientId, reportId, readOnly }: Props) {
  const dropMut = useDropFinding(clientId, reportId);
  const discardMut = useDiscardFinding(clientId, reportId);

  const isDropped = finding.state === "dropped";
  const isDiscarded = finding.state === "discarded";
  const isTerminal = isDropped || isDiscarded;

  const handleDrop = (e: React.MouseEvent) => {
    e.stopPropagation();
    dropMut.mutate(finding.finding_id, {
      onSuccess: () => toast.success("Finding dropped — re-eligible next cycle."),
      onError: () => toast.error("Failed to drop finding."),
    });
  };

  const handleDiscard = (e: React.MouseEvent) => {
    e.stopPropagation();
    discardMut.mutate(
      { findingId: finding.finding_id },
      {
        onSuccess: () => toast.success("Finding permanently discarded."),
        onError: () => toast.error("Failed to discard finding."),
      },
    );
  };

  return (
    <button
      type="button"
      className={cn(
        "w-full text-left rounded p-2 text-xs transition-colors",
        selected ? "bg-primary/10 border border-primary/30" : "hover:bg-muted",
        isTerminal && "opacity-50",
      )}
      onClick={onSelect}
      aria-pressed={selected}
      aria-label={`Finding: ${finding.drug} / ${finding.reaction}`}
    >
      <div className="flex items-start justify-between gap-1">
        <div className="min-w-0">
          <p className="font-medium truncate">{finding.drug}</p>
          <p className="text-muted-foreground truncate">{finding.reaction}</p>
          <span className={cn("font-medium capitalize", BUCKET_COLOR[finding.bucket])}>
            {finding.bucket}
          </span>
          {isTerminal && (
            <span className="ml-1 text-muted-foreground capitalize">· {finding.state}</span>
          )}
        </div>
        {!readOnly && !isTerminal && (
          <div className="flex gap-1 shrink-0 mt-0.5">
            <Button
              variant="ghost"
              size="sm"
              className="h-6 px-1.5 text-xs"
              onClick={handleDrop}
              disabled={dropMut.isPending}
              title="Drop — re-eligible next cycle"
            >
              Drop
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="h-6 px-1.5 text-xs text-destructive hover:text-destructive"
              onClick={handleDiscard}
              disabled={discardMut.isPending}
              title="Discard permanently"
            >
              Discard
            </Button>
          </div>
        )}
      </div>
    </button>
  );
}
