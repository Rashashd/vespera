/**
 * Severity (finding bucket) pill — brand signal colours per the design system:
 * emergency = solid red, urgent = red-tint, minor = teal-tint, positive =
 * blue-tint, irrelevant = neutral. Mono uppercase label.
 */
import type { FindingBucket } from "@/api/schemas";

const SEVERITY: Record<FindingBucket, string> = {
  emergency: "bg-destructive text-destructive-foreground",
  urgent:
    "border border-[#a33a36]/30 bg-[#a33a36]/12 text-[#a33a36] dark:border-[#c0706c]/30 dark:bg-[#c0706c]/15 dark:text-[#c0706c]",
  minor: "border border-primary/25 bg-primary/12 text-primary",
  positive:
    "border border-[#4a6fa0]/30 bg-[#4a6fa0]/12 text-[#4a6fa0] dark:border-[#6e9fc4]/30 dark:bg-[#6e9fc4]/15 dark:text-[#6e9fc4]",
  irrelevant: "border border-border bg-muted text-muted-foreground",
};

export function SeverityBadge({
  bucket,
  className = "",
}: {
  bucket: FindingBucket;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex items-center rounded-md px-2 py-0.5 font-mono text-[10px] font-medium uppercase tracking-[0.1em] ${SEVERITY[bucket]} ${className}`}
    >
      {bucket}
    </span>
  );
}
