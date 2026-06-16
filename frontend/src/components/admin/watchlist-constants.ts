// Shared option lists for watchlist editors. Cadence is limited to the values the
// DB CHECK constraint allows (daily/weekly/monthly) — `biweekly` exists in the enum
// but is rejected by ck_watchlists_cadence.
export const CADENCE_OPTIONS = [
  { value: "daily", label: "Daily" },
  { value: "weekly", label: "Weekly" },
  { value: "monthly", label: "Monthly" },
];

export const SEVERITY_OPTIONS = [
  { value: "non-serious", label: "Non-serious" },
  { value: "serious", label: "Serious" },
  { value: "life-threatening", label: "Life-threatening" },
];

export const POLICY_OPTIONS = [
  { value: "continue", label: "Continue (default)" },
  { value: "critical_only", label: "Critical only" },
  { value: "pause", label: "Pause" },
];

export const ITEM_TYPE_OPTIONS = [
  { value: "drug", label: "Drug" },
  { value: "mesh", label: "MeSH" },
  { value: "keyword", label: "Keyword" },
];
