import { X } from "lucide-react";
import { usePassage } from "@/api/hooks";
import { Button } from "./ui/button";
import { Separator } from "./ui/separator";
import { cn } from "@/lib/utils";
import type { CorroborationSource } from "@/api/schemas";

interface Props {
  clientId: number | null;
  chunkId: number | null;
  source: CorroborationSource | null;
  onClose: () => void;
}

export function PassageDrawer({ clientId, chunkId, source, onClose }: Props) {
  const { data: passage, isLoading, isError } = usePassage(clientId, chunkId, chunkId !== null);

  return (
    <aside
      className="fixed inset-y-0 right-0 w-[420px] border-l bg-card shadow-xl z-40 flex flex-col animate-slide-in"
      role="complementary"
      aria-label="Source passage"
    >
      <div className="flex items-center justify-between p-4">
        <h2 className="text-sm font-semibold">Source passage</h2>
        <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close passage drawer">
          <X className="h-4 w-4" />
        </Button>
      </div>
      <Separator />

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Citation metadata (always visible) */}
        {source && (
          <dl className="text-xs space-y-1 text-muted-foreground">
            {source.title && (
              <>
                <dt className="font-medium text-foreground">Title</dt>
                <dd>{source.title}</dd>
              </>
            )}
            {source.external_id && (
              <>
                <dt className="font-medium text-foreground">ID</dt>
                <dd>{source.external_id}</dd>
              </>
            )}
            {source.source_reliability && (
              <>
                <dt className="font-medium text-foreground">Reliability</dt>
                <dd className="capitalize">{source.source_reliability.replace(/_/g, " ")}</dd>
              </>
            )}
          </dl>
        )}

        <Separator />

        {/* Passage text */}
        {isLoading && <p className="text-sm text-muted-foreground">Loading passage…</p>}
        {(isError || (!isLoading && !passage)) && (
          <div className="rounded border border-dashed p-4 text-sm text-muted-foreground">
            <p className="font-medium">Passage unavailable</p>
            <p className="mt-1">The source text could not be retrieved. Citation metadata above is still valid.</p>
          </div>
        )}
        {passage && (
          <div className="space-y-2">
            {passage.section && (
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                {passage.section}
              </p>
            )}
            <blockquote className="text-sm leading-relaxed border-l-2 border-primary pl-3">
              {passage.text}
            </blockquote>
          </div>
        )}
      </div>
    </aside>
  );
}
