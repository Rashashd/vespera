import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

interface Props {
  deadline: string | null | undefined;
  className?: string;
}

function msUntil(deadline: string): number {
  return new Date(deadline).getTime() - Date.now();
}

function format(ms: number): string {
  if (ms < 0) return "Overdue";
  const h = Math.floor(ms / 3_600_000);
  const m = Math.floor((ms % 3_600_000) / 60_000);
  return `${h}h ${m}m`;
}

export function SlaCountdown({ deadline, className }: Props) {
  const [ms, setMs] = useState<number | null>(
    deadline ? msUntil(deadline) : null,
  );

  useEffect(() => {
    if (!deadline) return;
    const id = setInterval(() => setMs(msUntil(deadline)), 30_000);
    setMs(msUntil(deadline));
    return () => clearInterval(id);
  }, [deadline]);

  if (ms === null) return null;

  const isOverdue = ms < 0;
  const isDueSoon = !isOverdue && ms < 2 * 3_600_000;

  return (
    <span
      className={cn(
        "text-xs font-medium px-1.5 py-0.5 rounded",
        isOverdue
          ? "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400"
          : isDueSoon
            ? "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400"
            : "bg-muted text-muted-foreground",
        className,
      )}
      aria-label={`SLA: ${format(ms)}`}
    >
      {format(ms)}
    </span>
  );
}
