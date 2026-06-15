import { Pencil, Sigma, Link } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Claim } from "@/api/schemas";

interface Props {
  claim: Claim;
  onSourceClick?: () => void;
}

// Three visually distinct trust classes (FR-008 / design-system §12.4)
export function ProvenanceBadge({ claim, onSourceClick }: Props) {
  const p = claim.provenance;

  if (p === "drafted_grounded") {
    return (
      <button
        type="button"
        onClick={onSourceClick}
        disabled={!claim.source_ref}
        className={cn(
          "inline-flex items-center gap-1 text-xs px-1.5 py-0.5 rounded border",
          "border-primary/40 text-primary bg-primary/5 hover:bg-primary/10",
          !claim.source_ref && "opacity-50 cursor-default",
        )}
        aria-label="Grounded citation — click to view passage"
        title="Grounded — click to view passage"
      >
        <Link className="h-3 w-3" />
        grounded
      </button>
    );
  }

  if (p === "reviewer_attested") {
    return (
      <span
        className="inline-flex items-center gap-1 text-xs px-1.5 py-0.5 rounded border border-dashed border-amber-500/60 text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20"
        title="Reviewer-added claim (not grounded in a source passage)"
      >
        <Pencil className="h-3 w-3" />
        reviewer-added
      </span>
    );
  }

  // aggregated
  return (
    <span
      className="inline-flex items-center gap-1 text-xs px-1.5 py-0.5 rounded border border-slate-300 text-muted-foreground bg-muted"
      title="Aggregated from multiple sources"
    >
      <Sigma className="h-3 w-3" />
      aggregated
    </span>
  );
}
