/**
 * TanStack Query hooks for all data resources.
 * Each hook includes the acting clientId in the query key so switching clients refetches.
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, post } from "./client";
import {
  ReportSummarySchema,
  ReportResponseSchema,
  PassageResponseSchema,
  ReportFindingDetailSchema,
  PortalReportSummarySchema,
  CostDashboardSchema,
  OpsDashboardSchema,
  ClientSchema,
  WatchlistSchema,
  UserSchema,
  type ReportSummary,
  type ReportResponse,
  type PassageResponse,
  type ReportFindingDetail,
  type PortalReportSummary,
  type CostDashboard,
  type OpsDashboard,
  type Client,
  type Watchlist,
} from "./schemas";
import { z } from "zod";

// ── Auth ──────────────────────────────────────────────────────────────────────

export function useCurrentUser() {
  return useQuery({
    queryKey: ["me"],
    queryFn: () => get<unknown>("/auth/users/me").then((r) => UserSchema.parse(r)),
  });
}

// ── Clients (admin + acting-client switcher) ──────────────────────────────────

export function useClients() {
  return useQuery({
    queryKey: ["clients"],
    queryFn: () =>
      get<unknown[]>("/clients").then((rows) => z.array(ClientSchema).parse(rows)),
  });
}

export function useWatchlists(clientId: number | null) {
  return useQuery({
    queryKey: ["watchlists", clientId],
    queryFn: () =>
      get<unknown[]>(`/clients/${clientId}/watchlists`).then((rows) =>
        z.array(WatchlistSchema).parse(rows),
      ),
    enabled: clientId !== null,
  });
}

// ── Reviewer queue ────────────────────────────────────────────────────────────

export function useReportsQueue(clientId: number | null, page = 0, limit = 50) {
  return useQuery({
    queryKey: ["reports", "queue", clientId, page, limit],
    queryFn: () =>
      get<unknown[]>(
        `/clients/${clientId}/reports?limit=${limit}&offset=${page * limit}`,
      ).then((rows) => z.array(ReportSummarySchema).parse(rows)),
    enabled: clientId !== null,
  });
}

export function useAllReports(clientId: number | null, page = 0, limit = 50) {
  return useQuery({
    queryKey: ["reports", "all", clientId, page, limit],
    queryFn: () =>
      get<unknown[]>(
        `/clients/${clientId}/reports?status=all&limit=${limit}&offset=${page * limit}`,
      ).then((rows) => z.array(ReportSummarySchema).parse(rows)),
    enabled: clientId !== null,
  });
}

export function useReport(clientId: number | null, reportId: number | undefined) {
  return useQuery({
    queryKey: ["report", clientId, reportId],
    queryFn: () =>
      get<unknown>(`/clients/${clientId}/reports/${reportId}`).then((r) =>
        ReportResponseSchema.parse(r),
      ),
    enabled: clientId !== null && reportId !== undefined,
  });
}

export function useReportFindings(
  clientId: number | null,
  reportId: number | undefined,
) {
  return useQuery({
    queryKey: ["report-findings", clientId, reportId],
    queryFn: () =>
      get<unknown[]>(`/clients/${clientId}/reports/${reportId}/findings`).then(
        (rows) => z.array(ReportFindingDetailSchema).parse(rows),
      ),
    enabled: clientId !== null && reportId !== undefined,
  });
}

export function usePassage(
  clientId: number | null,
  chunkId: number | null,
  enabled: boolean,
) {
  return useQuery({
    queryKey: ["passage", clientId, chunkId],
    queryFn: () =>
      get<unknown>(`/clients/${clientId}/passages/${chunkId}`).then((r) =>
        PassageResponseSchema.parse(r),
      ),
    enabled: enabled && clientId !== null && chunkId !== null,
    retry: false,
  });
}

// ── Portal ────────────────────────────────────────────────────────────────────

export function usePortalReports(
  clientId: number | null,
  watchlistId?: number,
) {
  const qs = watchlistId ? `?watchlist_id=${watchlistId}` : "";
  return useQuery({
    queryKey: ["portal-reports", clientId, watchlistId],
    queryFn: () =>
      get<unknown[]>(`/clients/${clientId}/portal/reports${qs}`).then((rows) =>
        z.array(PortalReportSummarySchema).parse(rows),
      ),
    enabled: clientId !== null,
  });
}

// ── Dashboard ─────────────────────────────────────────────────────────────────

export function useUsageDashboard(clientId: number | null) {
  return useQuery({
    queryKey: ["usage", clientId],
    queryFn: () =>
      get<unknown>(`/clients/${clientId}/usage`).then((r) =>
        CostDashboardSchema.parse(r),
      ),
    enabled: clientId !== null,
  });
}

export function useOpsDashboard(clientId: number | null) {
  return useQuery({
    queryKey: ["metrics", clientId],
    queryFn: () =>
      get<unknown>(`/clients/${clientId}/metrics`).then((r) =>
        OpsDashboardSchema.parse(r),
      ),
    enabled: clientId !== null,
  });
}

// ── Mutations ─────────────────────────────────────────────────────────────────

export function useApprove(clientId: number | null, reportId: number | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => post(`/clients/${clientId}/reports/${reportId}/approve`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["reports"] });
      qc.invalidateQueries({ queryKey: ["report", clientId, reportId] });
    },
  });
}

export function useReject(clientId: number | null, reportId: number | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (comment: string) =>
      post(`/clients/${clientId}/reports/${reportId}/reject`, { comment }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["reports"] });
      qc.invalidateQueries({ queryKey: ["report", clientId, reportId] });
    },
  });
}

export function useDiscard(clientId: number | null, reportId: number | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (reason?: string) =>
      post(`/clients/${clientId}/reports/${reportId}/discard`, { reason }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["reports"] });
      qc.invalidateQueries({ queryKey: ["report", clientId, reportId] });
    },
  });
}

export function useEditApprove(clientId: number | null, reportId: number | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      draft_body: string;
      structured_fields: unknown[];
      comment: string;
    }) =>
      post(`/clients/${clientId}/reports/${reportId}/edit-approve`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["reports"] });
      qc.invalidateQueries({ queryKey: ["report", clientId, reportId] });
    },
  });
}

export function useDropFinding(
  clientId: number | null,
  reportId: number | undefined,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (findingId: number) =>
      post(
        `/clients/${clientId}/reports/${reportId}/findings/${findingId}/drop`,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["report-findings", clientId, reportId] });
      qc.invalidateQueries({ queryKey: ["report", clientId, reportId] });
    },
  });
}

export function useDiscardFinding(
  clientId: number | null,
  reportId: number | undefined,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ findingId, reason }: { findingId: number; reason?: string }) =>
      post(
        `/clients/${clientId}/reports/${reportId}/findings/${findingId}/discard`,
        { reason },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["report-findings", clientId, reportId] });
      qc.invalidateQueries({ queryKey: ["report", clientId, reportId] });
    },
  });
}

export function useTriggerIngest(
  clientId: number | null,
  watchlistId: number | undefined,
) {
  return useMutation({
    mutationFn: () =>
      post(`/clients/${clientId}/watchlists/${watchlistId}/ingest`),
  });
}
