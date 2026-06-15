/**
 * Zod schemas mirroring live backend responses.
 * corroboration_sources uses .passthrough() — it's list[dict]|null on the wire.
 */

import { z } from "zod";

// --- Enums ---

export const ClaimProvenance = z.enum([
  "drafted_grounded",
  "reviewer_attested",
  "aggregated",
]);

export const ReportStatus = z.enum([
  "drafted",
  "under_review",
  "approved",
  "rejected",
  "discarded",
  "needs_manual_revision",
]);

export const ReportType = z.enum(["expedited", "batch"]);

export const FindingBucket = z.enum(["emergency", "urgent", "minor", "positive", "irrelevant"]);

export const FindingReportState = z.enum(["included", "dropped", "discarded"]);

// --- Claim (structured_fields item) ---

export const ClaimSchema = z.object({
  text: z.string(),
  provenance: ClaimProvenance,
  source_ref: z.string().nullable().optional(),
});
export type Claim = z.infer<typeof ClaimSchema>;

// --- CorroborationSource (passthrough — dict on wire) ---

export const CorroborationSourceSchema = z
  .object({
    document_id: z.number().optional(),
    title: z.string().optional(),
    external_id: z.string().optional(),
    date: z.string().nullable().optional(),
    source_reliability: z.string().optional(),
    sources: z.array(z.string()).optional(),
    passage_chunk_ids: z.array(z.number()).optional(),
  })
  .passthrough();
export type CorroborationSource = z.infer<typeof CorroborationSourceSchema>;

// --- ReportSummary ---

export const ReportSummarySchema = z.object({
  id: z.number(),
  client_id: z.number(),
  report_type: ReportType,
  status: ReportStatus,
  corroboration_count: z.number(),
  revision_count: z.number(),
  sla_deadline: z.string().nullable().optional(),
  watchlist_id: z.number().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type ReportSummary = z.infer<typeof ReportSummarySchema>;

// --- ReportResponse (full detail) ---

export const ReviewerCommentSchema = z
  .object({
    comment: z.string().optional(),
    reviewer_id: z.number().optional(),
    round: z.number().optional(),
    created_at: z.string().optional(),
  })
  .passthrough();

export const ReportResponseSchema = ReportSummarySchema.extend({
  structured_fields: z.array(ClaimSchema),
  draft_body: z.string().nullable().optional(),
  corroboration_sources: z.array(CorroborationSourceSchema).nullable().optional(),
  reviewer_comments: z.array(ReviewerCommentSchema),
  cycle_period_start: z.string().nullable().optional(),
  cycle_period_end: z.string().nullable().optional(),
});
export type ReportResponse = z.infer<typeof ReportResponseSchema>;

// --- PassageResponse (FR-029) ---

export const PassageResponseSchema = z.object({
  chunk_id: z.number(),
  text: z.string(),
  section: z.string().nullable().optional(),
  source_reliability: z.string(),
  date: z.string().nullable().optional(),
  document_id: z.number(),
  title: z.string().nullable().optional(),
  external_id: z.string().nullable().optional(),
});
export type PassageResponse = z.infer<typeof PassageResponseSchema>;

// --- ReportFindingDetail (FR-031) ---

export const ReportFindingDetailSchema = z.object({
  id: z.number(),
  report_id: z.number(),
  finding_id: z.number(),
  drug: z.string(),
  reaction: z.string(),
  bucket: FindingBucket,
  state: FindingReportState,
  created_at: z.string(),
});
export type ReportFindingDetail = z.infer<typeof ReportFindingDetailSchema>;

// --- PortalReportSummary (FR-030) ---

export const DeliveryStatus = z.enum([
  "approved_pending_delivery",
  "sent",
  "delivered",
  "delivery_failed",
]);
export type DeliveryStatus = z.infer<typeof DeliveryStatus>;

export const PortalReportSummarySchema = z.object({
  id: z.number(),
  report_type: ReportType,
  status: ReportStatus,
  delivery_status: DeliveryStatus,
  watchlist_id: z.number().nullable().optional(),
  corroboration_count: z.number(),
  sla_deadline: z.string().nullable().optional(),
  cycle_period_start: z.string().nullable().optional(),
  cycle_period_end: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type PortalReportSummary = z.infer<typeof PortalReportSummarySchema>;

// --- Auth / User ---

export const UserSchema = z.object({
  id: z.number(),
  email: z.string(),
  role: z.string().nullable().optional(),
  user_type: z.enum(["staff", "client"]),
  client_id: z.number().nullable().optional(),
  is_active: z.boolean(),
});
export type User = z.infer<typeof UserSchema>;

// --- Client (admin console) ---

export const ClientSchema = z.object({
  id: z.number(),
  name: z.string(),
  status: z.string(),
  cadence: z.string().optional(),
  custom_severity_keywords: z.array(z.string()).optional(),
});
export type Client = z.infer<typeof ClientSchema>;

// --- Watchlist ---

export const WatchlistSchema = z.object({
  id: z.number(),
  client_id: z.number(),
  name: z.string(),
  status: z.string(),
});
export type Watchlist = z.infer<typeof WatchlistSchema>;

// --- Cost / Ops Dashboard ---

export const CallSiteBreakdownSchema = z.object({
  cost_usd: z.string(),
  calls: z.number(),
});

export const CostDashboardSchema = z.object({
  client_id: z.number(),
  total_cost_usd: z.string(),
  total_input_tokens: z.number(),
  total_output_tokens: z.number(),
  call_count: z.number(),
  by_call_site: z.record(CallSiteBreakdownSchema),
  window: z.object({ from: z.string().nullable(), to: z.string().nullable() }),
});
export type CostDashboard = z.infer<typeof CostDashboardSchema>;

export const OpsDashboardSchema = z.object({
  client_id: z.number(),
  by_status: z.record(z.number()),
  queue: z.object({ pending: z.number(), expedited: z.number(), batch: z.number() }),
  sla: z.object({ overdue: z.number(), due_soon: z.number(), met_pct: z.number() }),
  redraft: z.object({ avg_revisions: z.number(), hit_cap: z.number() }),
  delivery: z.null(),
  window: z.object({ from: z.string().nullable(), to: z.string().nullable() }),
});
export type OpsDashboard = z.infer<typeof OpsDashboardSchema>;
