import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, AlertTriangle } from "lucide-react";
import { useReport, useReportFindings } from "@/api/hooks";
import { CitationPanel } from "./CitationPanel";
import { PassageDrawer } from "./PassageDrawer";
import { ProvenanceBadge } from "./ProvenanceBadge";
import { ReviewerActions } from "./ReviewerActions";
import { RevisionHistory } from "./RevisionHistory";
import { SlaCountdown } from "./SlaCountdown";
import { DeliveryStatusChip } from "./DeliveryStatusChip";
import { ReportStatusBadge } from "./ReportStatusBadge";
import { SeverityBadge } from "./SeverityBadge";
import { FindingRow } from "./FindingRow";
import { DownloadReportButton } from "./DownloadReportButton";
import { Button } from "./ui/button";
import { Separator } from "./ui/separator";
import { cn } from "@/lib/utils";
import type { Claim, CorroborationSource } from "@/api/schemas";

interface Props {
  clientId: number | null;
  reportId: number;
  mode: "queue" | "all-reports" | "portal";
}

const BUCKET_CLASSES: Record<string, string> = {
  emergency: "severity-bar-emergency",
  urgent: "severity-bar-urgent",
  minor: "severity-bar-minor",
  positive: "severity-bar-positive",
};

const CLINICAL_PRIORITY = ["Drug", "Reaction", "Severity", "Causality"];

function sortClaims(claims: Claim[]): Claim[] {
  return [...claims].sort((a, b) => {
    const ai = CLINICAL_PRIORITY.findIndex((k) => a.text.toLowerCase().startsWith(k.toLowerCase()));
    const bi = CLINICAL_PRIORITY.findIndex((k) => b.text.toLowerCase().startsWith(k.toLowerCase()));
    return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
  });
}

export function ReportDetail({ clientId, reportId, mode }: Props) {
  const navigate = useNavigate();
  const { data: report, isLoading, isError, refetch } = useReport(clientId, reportId);
  const { data: findings = [] } = useReportFindings(clientId, reportId);

  const [selectedFindingId, setSelectedFindingId] = useState<number | null>(null);
  // Citation review tracking (FR-040) — per-session, client-side
  const [reviewedChunks, setReviewedChunks] = useState<Set<string>>(new Set());
  // Shared passage drawer — opened from a source row or a claim's inline [n]
  const [openChunkId, setOpenChunkId] = useState<number | null>(null);
  const [openSource, setOpenSource] = useState<CorroborationSource | null>(null);

  const isReadOnly = mode !== "queue";
  const isBatch = report?.report_type === "batch";
  const isMidRedraft = report?.status === "under_review";

  if (isLoading) {
    return <div className="p-8 text-muted-foreground">Loading report…</div>;
  }
  if (isError || !report) {
    return <div className="p-8 text-destructive">Report not found.</div>;
  }

  const sources = report.corroboration_sources ?? [];
  const allChunkIds = sources.flatMap((s) => s.passage_chunk_ids ?? []).map(String);
  const citationProgress = {
    reviewed: reviewedChunks.size,
    total: allChunkIds.length,
  };

  // Reference numbering: map each source's chunk ids → its 1-based reference
  // number, so a claim's source_ref resolves to the same [n] shown in References.
  const chunkToSourceIdx = new Map<number, number>();
  sources.forEach((s, i) =>
    (s.passage_chunk_ids ?? []).forEach((cid) => {
      if (!chunkToSourceIdx.has(cid)) chunkToSourceIdx.set(cid, i);
    }),
  );
  const markReviewed = (ref: string) =>
    setReviewedChunks((prev) => new Set([...prev, ref]));
  const refNumber = (ref?: string | null): number | null => {
    if (!ref) return null;
    const idx = chunkToSourceIdx.get(parseInt(ref, 10));
    return idx == null ? null : idx + 1;
  };
  const openByRef = (ref: string) => {
    const cid = parseInt(ref, 10);
    const idx = chunkToSourceIdx.get(cid);
    setOpenSource(idx == null ? null : sources[idx]);
    setOpenChunkId(Number.isNaN(cid) ? null : cid);
    markReviewed(ref);
  };
  const openSourceRow = (src: CorroborationSource) => {
    const cid = src.passage_chunk_ids?.[0] ?? null;
    setOpenSource(src);
    setOpenChunkId(cid);
    if (cid != null) markReviewed(String(cid));
  };

  const backPath = mode === "queue" ? "/queue" : mode === "all-reports" ? "/reports" : "/portal";

  // Primary finding drives the severity bar + header title.
  const primaryFinding = findings.find((f) => f.state === "included") ?? findings[0];
  const primaryBucket = primaryFinding?.bucket ?? "minor";
  const title = primaryFinding
    ? `${primaryFinding.drug} — ${primaryFinding.reaction}`
    : `Report #${report.id}`;

  return (
    <div className={cn("flex flex-col h-full", BUCKET_CLASSES[primaryBucket])}>
      {/* Header */}
      <div className="border-b bg-card px-6 py-4">
        <div className="mb-3 flex items-center justify-between gap-3">
          <Button variant="ghost" size="sm" onClick={() => navigate(backPath)} aria-label="Back">
            <ArrowLeft className="mr-1 h-4 w-4" />
            Back
          </Button>
          <DownloadReportButton />
        </div>
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="mb-1.5 flex items-center gap-2">
              <SeverityBadge bucket={primaryBucket} />
              <span className="font-mono text-[10.5px] uppercase tracking-[0.14em] text-[#4a6580] dark:text-[#8095a8]">
                {report.report_type}
              </span>
              {report.sla_deadline && <SlaCountdown deadline={report.sla_deadline} />}
            </div>
            <h2 className="truncate font-display text-[22px] font-semibold text-foreground">
              {title}
            </h2>
            <p className="mt-0.5 font-mono text-[11px] text-[#4a6580] dark:text-[#8095a8]">
              Report #{report.id}
            </p>
          </div>
          <div className="flex flex-shrink-0 flex-col items-end gap-2">
            <ReportStatusBadge status={report.status} />
            <DeliveryStatusChip status={report.status} />
          </div>
        </div>
      </div>

      {/* Mid-redraft warning */}
      {isMidRedraft && !isReadOnly && (
        <div className="flex items-center gap-2 px-4 py-2 bg-amber-50 dark:bg-amber-900/20 border-b text-amber-700 dark:text-amber-400 text-sm">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          This report is currently being redrafted — actions are unavailable until drafting completes.
        </div>
      )}

      <div className="flex flex-1 overflow-hidden">
        {/* Left rail: batch findings list */}
        {isBatch && findings.length > 0 && (
          <aside className="w-64 border-r overflow-y-auto p-3 space-y-1 shrink-0">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground px-1 mb-2">
              Findings ({findings.length})
            </h2>
            {findings.map((f) => (
              <FindingRow
                key={f.id}
                finding={f}
                selected={selectedFindingId === f.finding_id}
                onSelect={() => setSelectedFindingId(f.finding_id)}
                clientId={clientId}
                reportId={reportId}
                readOnly={isReadOnly}
              />
            ))}
          </aside>
        )}

        {/* Center: claims + citations */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {/* Citation review progress (FR-040) */}
          {!isReadOnly && allChunkIds.length > 0 && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <span>
                {citationProgress.reviewed} of {citationProgress.total} sources reviewed
              </span>
              <div className="flex-1 h-1 rounded-full bg-muted overflow-hidden">
                <div
                  className="h-full bg-primary transition-all"
                  style={{
                    width: `${citationProgress.total ? (citationProgress.reviewed / citationProgress.total) * 100 : 0}%`,
                  }}
                />
              </div>
            </div>
          )}

          {/* Structured claims (clinical hierarchy) */}
          <section aria-label="Structured claims">
            <h2 className="mb-3 font-display text-[15px] font-semibold text-foreground">
              Structured claims
            </h2>
            <ol className="space-y-3">
              {sortClaims(report.structured_fields).map((claim, i) => {
                const n = refNumber(claim.source_ref);
                return (
                  <li key={i} className="flex items-start gap-2 text-sm">
                    <ProvenanceBadge
                      claim={claim}
                      onSourceClick={() => {
                        if (claim.source_ref) openByRef(claim.source_ref);
                      }}
                    />
                    <span className="flex-1">
                      {claim.text}
                      {n != null && (
                        <button
                          type="button"
                          onClick={() => openByRef(claim.source_ref!)}
                          className="ml-1 align-super text-[11px] font-medium text-primary hover:underline"
                          aria-label={`View reference ${n}`}
                        >
                          [{n}]
                        </button>
                      )}
                    </span>
                  </li>
                );
              })}
            </ol>
          </section>

          {/* Draft body */}
          {report.draft_body && (
            <section aria-label="Report narrative">
              <h2 className="mb-2 font-display text-[15px] font-semibold text-foreground">
                Report narrative
              </h2>
              <div className="prose prose-sm max-w-none whitespace-pre-wrap rounded-xl border bg-muted/30 p-4 text-sm dark:prose-invert">
                {report.draft_body}
              </div>
            </section>
          )}

          <Separator />

          {/* Citations */}
          <CitationPanel
            sources={sources}
            corroborationCount={report.corroboration_count}
            onOpen={(src) => openSourceRow(src)}
          />

          <Separator />

          {/* Revision history */}
          {!isReadOnly && (
            <RevisionHistory
              comments={report.reviewer_comments}
              revisionCount={report.revision_count}
            />
          )}
        </div>
      </div>

      {/* Action bar (reviewer-only, not mid-redraft) */}
      {!isReadOnly && !isMidRedraft && (
        <ReviewerActions
          clientId={clientId}
          report={report}
          citationReviewProgress={citationProgress}
          onAction={() => refetch()}
        />
      )}

      {/* Shared passage drawer (opened from a source row or a claim's [n]) */}
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
    </div>
  );
}
