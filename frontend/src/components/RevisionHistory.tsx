import type { ReportResponse } from "@/api/schemas";
import { formatDistanceToNow } from "@/lib/dateUtils";

interface Props {
  comments: ReportResponse["reviewer_comments"];
  revisionCount: number;
  redraftCap?: number;
}

export function RevisionHistory({ comments, revisionCount, redraftCap = 3 }: Props) {
  if (comments.length === 0 && revisionCount === 0) return null;

  return (
    <section aria-label="Revision history" className="space-y-2">
      <h3 className="text-sm font-medium text-muted-foreground">
        Revision history — round {revisionCount} of {redraftCap}
      </h3>
      {revisionCount >= redraftCap && (
        <p className="text-xs text-destructive">
          Rejection cap reached — next rejection will mark as "needs manual revision"
        </p>
      )}
      <ol className="space-y-2">
        {comments.map((c, i) => (
          <li key={i} className="rounded border bg-muted/50 p-3 text-sm space-y-1">
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium">Round {(c as { round?: number }).round ?? i + 1}</span>
              {(c as { created_at?: string }).created_at && (
                <span className="text-xs text-muted-foreground">
                  {formatDistanceToNow((c as { created_at: string }).created_at)}
                </span>
              )}
            </div>
            {(c as { comment?: string }).comment && (
              <p className="text-muted-foreground">{(c as { comment: string }).comment}</p>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}
