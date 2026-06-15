import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { PassageDrawer } from "./PassageDrawer";
import type { CorroborationSource } from "@/api/schemas";

interface Props {
  clientId: number | null;
  sources: CorroborationSource[] | null | undefined;
  corroborationCount: number;
}

export function CitationPanel({ clientId, sources, corroborationCount }: Props) {
  const [openChunkId, setOpenChunkId] = useState<number | null>(null);
  const [openSource, setOpenSource] = useState<CorroborationSource | null>(null);

  if (!sources || sources.length === 0) {
    return (
      <div className="rounded border bg-muted/50 p-4 text-sm text-muted-foreground">
        No corroboration sources.
      </div>
    );
  }

  const handleClick = (src: CorroborationSource) => {
    const chunkIds = src.passage_chunk_ids;
    const chunkId = chunkIds && chunkIds.length > 0 ? chunkIds[0] : null;
    setOpenSource(src);
    setOpenChunkId(chunkId);
  };

  return (
    <>
      <section aria-label="Corroboration sources">
        <h3 className="text-sm font-medium text-muted-foreground mb-2">
          {corroborationCount} corroborating source{corroborationCount !== 1 ? "s" : ""}
        </h3>
        <ol className="space-y-2">
          {sources.map((src, i) => (
            <li key={i}>
              <button
                type="button"
                className={cn(
                  "w-full text-left rounded border p-3 text-sm transition-colors",
                  "hover:border-primary/50 hover:bg-primary/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                )}
                onClick={() => handleClick(src)}
                aria-label={`Open passage for ${src.title ?? "source " + (i + 1)}`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="space-y-0.5 min-w-0">
                    <p className="font-medium truncate">{src.title ?? "Untitled source"}</p>
                    {src.external_id && (
                      <p className="text-xs text-muted-foreground">{src.external_id}</p>
                    )}
                    {src.source_reliability && (
                      <p className="text-xs text-muted-foreground capitalize">
                        {src.source_reliability.replace(/_/g, " ")}
                      </p>
                    )}
                  </div>
                  <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground mt-0.5" />
                </div>
              </button>
            </li>
          ))}
        </ol>
      </section>

      {openChunkId !== null && (
        <PassageDrawer
          clientId={clientId}
          chunkId={openChunkId}
          source={openSource}
          onClose={() => {
            setOpenChunkId(null);
            setOpenSource(null);
          }}
        />
      )}
    </>
  );
}
