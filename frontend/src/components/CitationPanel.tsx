import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import type { CorroborationSource } from "@/api/schemas";

interface Props {
  sources: CorroborationSource[] | null | undefined;
  corroborationCount: number;
  /** Open the chunk drawer for a source (the parent owns the drawer). */
  onOpen: (src: CorroborationSource, number: number) => void;
}

/**
 * Numbered "References" list. Each source is a clickable [n] row that asks the
 * parent to open the passage drawer — so a claim's inline [n] and the matching
 * reference row both surface the same chunk.
 */
export function CitationPanel({ sources, corroborationCount, onOpen }: Props) {
  if (!sources || sources.length === 0) {
    return (
      <div className="rounded-xl border bg-muted/50 p-4 text-sm text-muted-foreground">
        No corroboration sources.
      </div>
    );
  }

  return (
    <section aria-label="References">
      <h3 className="mb-3 font-display text-[15px] font-semibold text-foreground">
        References — {corroborationCount} corroborating source
        {corroborationCount !== 1 ? "s" : ""}
      </h3>
      <ol className="space-y-2">
        {sources.map((src, i) => (
          <li key={i}>
            <button
              type="button"
              className={cn(
                "flex w-full items-start gap-3 rounded-xl border p-3 text-left text-sm transition-colors",
                "hover:border-primary/50 hover:bg-primary/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              )}
              onClick={() => onOpen(src, i + 1)}
              aria-label={`Open passage for reference ${i + 1}: ${src.title ?? "source " + (i + 1)}`}
            >
              <span className="mt-0.5 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-md bg-primary/12 font-mono text-[11px] font-medium text-primary">
                {i + 1}
              </span>
              <span className="min-w-0 flex-1 space-y-0.5">
                <span className="block truncate font-medium text-foreground">
                  {src.title ?? "Untitled source"}
                </span>
                {src.external_id && (
                  <span className="block text-xs text-muted-foreground">
                    {src.external_id}
                  </span>
                )}
                {src.source_reliability && (
                  <span className="block text-xs capitalize text-muted-foreground">
                    {src.source_reliability.replace(/_/g, " ")}
                  </span>
                )}
              </span>
              <ChevronRight className="mt-0.5 h-4 w-4 flex-shrink-0 text-muted-foreground" />
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}
