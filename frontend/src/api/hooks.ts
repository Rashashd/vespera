/**
 * TanStack Query hooks for all data resources.
 * Each hook includes the acting clientId in the query key so switching clients refetches.
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, post, patch, del } from "./client";
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
  AuditEntrySchema,
  DeadLetterSchema,
  UserSchema,
  StaffUserSchema,
  ClientUserSchema,
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

export function useReport(
  clientId: number | null,
  reportId: number | undefined,
  portal = false,
) {
  // Client-portal users hit the portal-safe endpoint; staff hit the reviewer endpoint
  // (reviewer route is require_reviewer, so client users would 404 on it).
  const path = portal ? "portal/reports" : "reports";
  return useQuery({
    queryKey: ["report", clientId, reportId, portal],
    queryFn: () =>
      get<unknown>(`/clients/${clientId}/${path}/${reportId}`).then((r) =>
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

// ── Audit log (staff oversight) ─────────────────────────────────────────────────

export function useAuditLog(params: {
  category?: string;
  clientId?: number | null;
}) {
  const qs = new URLSearchParams();
  if (params.category && params.category !== "all") qs.set("category", params.category);
  if (params.clientId != null) qs.set("client_id", String(params.clientId));
  const query = qs.toString();
  return useQuery({
    queryKey: ["audit", params.category ?? "all", params.clientId ?? null],
    queryFn: () =>
      get<unknown[]>(`/audit${query ? `?${query}` : ""}`).then((rows) =>
        z.array(AuditEntrySchema).parse(rows),
      ),
  });
}

// ── Dead-letter / failed jobs (staff) ───────────────────────────────────────────

export function useDeadLetters(params: {
  resolved: boolean;
  clientId?: number | null;
  limit?: number;
}) {
  const qs = new URLSearchParams();
  qs.set("resolved", String(params.resolved));
  if (params.clientId != null) qs.set("client_id", String(params.clientId));
  if (params.limit) qs.set("limit", String(params.limit));
  return useQuery({
    queryKey: ["dead-letters", params.resolved, params.clientId ?? null, params.limit ?? 50],
    queryFn: () =>
      get<unknown[]>(`/admin/dead-letters?${qs.toString()}`).then((rows) =>
        z.array(DeadLetterSchema).parse(rows),
      ),
  });
}

export function useResolveDeadLetter() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => post(`/admin/dead-letters/${id}/resolve`),
    // Refetch on success AND on 409 (already-resolved) so the list reflects truth.
    onSettled: () => qc.invalidateQueries({ queryKey: ["dead-letters"] }),
  });
}

// ── Client management (manager / admin) ─────────────────────────────────────────

export interface CreateClientBody {
  name: string;
  report_email_regular?: string | null;
  report_email_urgent?: string | null;
  urgent_severity_threshold?: string | null;
}

export function useCreateClient() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateClientBody) =>
      post<Client>("/clients", body).then((r) => ClientSchema.parse(r)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["clients"] }),
  });
}

export function useSuspendClient() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (clientId: number) => post(`/clients/${clientId}/suspend`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["clients"] }),
  });
}

export function useReactivateClient() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (clientId: number) => post(`/clients/${clientId}/reactivate`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["clients"] }),
  });
}

export function useSetSeverityKeywords(clientId: number | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (keywords: string[]) =>
      patch<Client>(`/clients/${clientId}/severity-keywords`, { keywords }).then((r) =>
        ClientSchema.parse(r),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["clients"] }),
  });
}

// ── Watchlist management (manager / admin) ──────────────────────────────────────

export interface CreateWatchlistBody {
  name: string;
  cadence: string;
  severity_threshold: string;
  budget_amount?: string | null;
  budget_exceeded_policy: string;
  items: { item_type: string; value: string }[];
}

export function useCreateWatchlist(clientId: number | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateWatchlistBody) =>
      post<Watchlist>(`/clients/${clientId}/watchlists`, body).then((r) =>
        WatchlistSchema.parse(r),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlists", clientId] }),
  });
}

export interface UpdateWatchlistBody {
  name?: string;
  cadence?: string;
  severity_threshold?: string;
  budget_amount?: string | null;
  budget_exceeded_policy?: string;
  is_active?: boolean;
}

export function useUpdateWatchlist(clientId: number | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      watchlistId,
      body,
    }: {
      watchlistId: number;
      body: UpdateWatchlistBody;
    }) =>
      patch<Watchlist>(`/clients/${clientId}/watchlists/${watchlistId}`, body).then((r) =>
        WatchlistSchema.parse(r),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlists", clientId] }),
  });
}

export function useAddWatchlistItem(clientId: number | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      watchlistId,
      item_type,
      value,
    }: {
      watchlistId: number;
      item_type: string;
      value: string;
    }) =>
      post(`/clients/${clientId}/watchlists/${watchlistId}/items`, { item_type, value }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlists", clientId] }),
  });
}

export function useRemoveWatchlistItem(clientId: number | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ watchlistId, itemId }: { watchlistId: number; itemId: number }) =>
      del(`/clients/${clientId}/watchlists/${watchlistId}/items/${itemId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlists", clientId] }),
  });
}

// ── Account management — staff (manager) + client-users (admin) — spec 13 US4 ───

export function useStaff() {
  return useQuery({
    queryKey: ["staff"],
    queryFn: () =>
      get<unknown[]>("/staff").then((rows) => z.array(StaffUserSchema).parse(rows)),
  });
}

export function useCreateStaff() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string; password: string; role: string }) =>
      post("/staff", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["staff"] }),
  });
}

export function useUpdateStaff() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      userId,
      body,
    }: {
      userId: number;
      body: { role?: string; is_active?: boolean };
    }) => patch(`/staff/${userId}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["staff"] }),
  });
}

export function useClientUsers(clientId: number | null) {
  return useQuery({
    queryKey: ["client-users", clientId],
    queryFn: () =>
      get<unknown[]>(`/clients/${clientId}/users`).then((rows) =>
        z.array(ClientUserSchema).parse(rows),
      ),
    enabled: clientId !== null,
  });
}

export interface CreateClientUserBody {
  email: string;
  password: string;
  client_scope: string;
  min_severity?: string | null;
  watchlist_ids: number[];
}

export function useCreateClientUser(clientId: number | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateClientUserBody) => post(`/clients/${clientId}/users`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["client-users", clientId] }),
  });
}

export function useUpdateClientUser(clientId: number | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      userId,
      body,
    }: {
      userId: number;
      body: {
        client_scope?: string;
        min_severity?: string | null;
        watchlist_ids?: number[];
        is_active?: boolean;
      };
    }) => patch(`/clients/${clientId}/users/${userId}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["client-users", clientId] }),
  });
}
