import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, AlertTriangle } from "lucide-react";
import { useReport, useReportFindings } from "@/api/hooks";
import { CitationPanel } from "./CitationPanel";
import { ProvenanceBadge } from "./ProvenanceBadge";
import { ReviewerActions } from "./ReviewerActions";
import { RevisionHistory } from "./RevisionHistory";
import { SlaCountdown } from "./SlaCountdown";
import { DeliveryStatusChip } from "./DeliveryStatusChip";
import { FindingRow } from "./FindingRow";
import { DownloadReportButton } from "./DownloadReportButton";
import { Button } from "./ui/button";
import { Badge } from "./ui/badge";
import { Separator } from "./ui/separator";
import { cn } from "@/lib/utils";
import type { Claim } from "@/api/schemas";

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

  const backPath = mode === "queue" ? "/queue" : mode === "all-reports" ? "/reports" : "/portal";

  // Find the bucket from the first included finding for the severity bar
  const primaryBucket = findings.find((f) => f.state === "included")?.bucket ?? "minor";

  return (
    <div className={cn("flex flex-col h-full", BUCKET_CLASSES[primaryBucket])}>
      {/* Header */}
      <div className="flex items-center gap-3 p-4 border-b bg-card">
        <Button variant="ghost" size="sm" onClick={() => navigate(backPath)} aria-label="Back">
          <ArrowLeft className="h-4 w-4 mr-1" />
          Back
        </Button>
        <div className="flex-1 flex items-center gap-2 flex-wrap">
          <span className="font-semibold text-sm">Report #{report.id}</span>
          <Badge variant="outline" className="capitalize">{report.report_type}</Badge>
          <Badge variant="outline" className="capitalize">{report.status.replace(/_/g, " ")}</Badge>
          {report.sla_deadline && <SlaCountdown deadline={report.sla_deadline} />}
          <DeliveryStatusChip status={report.status} />
        </div>
        <DownloadReportButton />
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
            <h2 className="text-sm font-semibold mb-3">Structured claims</h2>
            <ol className="space-y-3">
              {sortClaims(report.structured_fields).map((claim, i) => (
                <li key={i} className="flex items-start gap-2 text-sm">
                  <ProvenanceBadge
                    claim={claim}
                    onSourceClick={() => {
                      if (claim.source_ref) {
                        setReviewedChunks((s) => new Set([...s, claim.source_ref!]));
                      }
                    }}
                  />
                  <span className="flex-1">{claim.text}</span>
                </li>
              ))}
            </ol>
          </section>

          {/* Draft body */}
          {report.draft_body && (
            <section aria-label="Report narrative">
              <h2 className="text-sm font-semibold mb-2">Report narrative</h2>
              <div className="prose prose-sm dark:prose-invert max-w-none rounded border bg-muted/30 p-4 whitespace-pre-wrap text-sm">
                {report.draft_body}
              </div>
            </section>
          )}

          <Separator />

          {/* Citations */}
          <CitationPanel
            clientId={clientId}
            sources={sources}
            corroborationCount={report.corroboration_count}
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
    </div>
  );
}
