/**
 * Report-status chip — a coloured dot + label for a ReportStatus, in the
 * brand mono label style. Reused across the queue, all-reports list, and the
 * report-detail header so status reads consistently everywhere.
 */
import type { ReportStatus } from "@/api/schemas";

const STATUS: Record<
  ReportStatus,
  { label: string; dot: string }
> = {
  drafted: { label: "Drafted", dot: "bg-[#b07a1e] dark:bg-[#d9a441]" },
  under_review: { label: "Pending review", dot: "bg-[#b07a1e] dark:bg-[#d9a441]" },
  approved: { label: "Approved", dot: "bg-primary" },
  rejected: { label: "Sent back", dot: "bg-[#a33a36] dark:bg-[#c0706c]" },
  needs_manual_revision: {
    label: "Needs revision",
    dot: "bg-[#a33a36] dark:bg-[#c0706c]",
  },
  discarded: { label: "Discarded", dot: "bg-muted-foreground" },
};

export function ReportStatusBadge({ status }: { status: ReportStatus }) {
  const s = STATUS[status];
  return (
    <span className="inline-flex items-center gap-1.5 font-mono text-[10.5px] uppercase tracking-[0.1em] text-[#4a6580] dark:text-[#8095a8]">
      <span className={`h-2 w-2 rounded-full ${s.dot}`} aria-hidden="true" />
      {s.label}
    </span>
  );
}
