import { useState } from "react";
import { toast } from "sonner";
import { useApprove, useReject, useDiscard } from "@/api/hooks";
import { ApiError } from "@/api/client";
import { Button } from "./ui/button";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogAction,
  AlertDialogCancel,
} from "./ui/alert-dialog";
import type { ReportResponse } from "@/api/schemas";

interface Props {
  clientId: number | null;
  report: ReportResponse;
  citationReviewProgress?: { reviewed: number; total: number };
  onAction?: () => void;
}

export function ReviewerActions({ clientId, report, citationReviewProgress, onAction }: Props) {
  const [showReject, setShowReject] = useState(false);
  const [showDiscard, setShowDiscard] = useState(false);
  const [showApproveGate, setShowApproveGate] = useState(false);
  const [rejectComment, setRejectComment] = useState("");

  const redraftCap = 3;
  const atCap = report.revision_count >= redraftCap;

  const approveMut = useApprove(clientId, report.id);
  const rejectMut = useReject(clientId, report.id);
  const discardMut = useDiscard(clientId, report.id);

  const handleError = (err: unknown) => {
    if (err instanceof ApiError && err.status === 409) {
      toast.error("Conflict: report was updated since you opened it. Refreshing…");
      onAction?.();
    } else {
      toast.error("Action failed. Please try again.");
    }
  };

  const doApprove = () => {
    approveMut.mutate(undefined, {
      onSuccess: () => {
        toast.success("Report approved.");
        onAction?.();
      },
      onError: handleError,
    });
  };

  const handleApproveClick = () => {
    const { reviewed, total } = citationReviewProgress ?? { reviewed: 0, total: 0 };
    if (total > 0 && reviewed < total) {
      setShowApproveGate(true);
    } else {
      doApprove();
    }
  };

  const handleReject = () => {
    if (!rejectComment.trim()) return;
    rejectMut.mutate(rejectComment, {
      onSuccess: () => {
        toast.success(
          atCap
            ? "Report marked as needs-manual-revision (cap reached)."
            : "Report sent for redraft.",
        );
        setShowReject(false);
        setRejectComment("");
        onAction?.();
      },
      onError: handleError,
    });
  };

  const handleDiscard = () => {
    discardMut.mutate(undefined, {
      onSuccess: () => {
        toast.success("Report discarded.");
        setShowDiscard(false);
        onAction?.();
      },
      onError: handleError,
    });
  };

  const isPending =
    approveMut.isPending || rejectMut.isPending || discardMut.isPending;

  return (
    <>
      {/* Single sticky action bar */}
      <div className="sticky bottom-0 bg-background border-t p-4 flex items-center gap-3 justify-end">
        <Button
          variant="outline"
          size="sm"
          onClick={() => setShowDiscard(true)}
          disabled={isPending}
        >
          Discard
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setShowReject(true)}
          disabled={isPending}
        >
          Reject{atCap ? " (cap)" : ""}
        </Button>
        <Button
          size="sm"
          onClick={handleApproveClick}
          disabled={isPending}
        >
          {approveMut.isPending ? "Approving…" : "Approve"}
        </Button>
      </div>

      {/* Soft approve gate (FR-040) — non-blocking */}
      <AlertDialog open={showApproveGate} onOpenChange={setShowApproveGate}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Not all citations reviewed</AlertDialogTitle>
            <AlertDialogDescription>
              {citationReviewProgress?.reviewed ?? 0} of {citationReviewProgress?.total ?? 0} sources
              reviewed. You can still approve — this is a reminder only.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Review more</AlertDialogCancel>
            <AlertDialogAction onClick={doApprove}>Approve anyway</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Reject dialog */}
      <AlertDialog open={showReject} onOpenChange={setShowReject}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Reject{atCap ? " — cap reached" : ` (round ${report.revision_count + 1} of ${redraftCap})`}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {atCap
                ? "This will mark the report as needs-manual-revision (no further auto-redraft)."
                : "The report will be returned for redraft. A comment is required."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <textarea
            className="w-full rounded border bg-background p-2 text-sm min-h-[80px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            placeholder="Rejection comment (required)…"
            value={rejectComment}
            onChange={(e) => setRejectComment(e.target.value)}
            aria-label="Rejection comment"
          />
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={handleReject}
              disabled={!rejectComment.trim() || rejectMut.isPending}
            >
              {rejectMut.isPending ? "Rejecting…" : "Reject"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Discard dialog */}
      <AlertDialog open={showDiscard} onOpenChange={setShowDiscard}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Discard report?</AlertDialogTitle>
            <AlertDialogDescription>
              This is permanent and cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={handleDiscard}
              disabled={discardMut.isPending}
            >
              {discardMut.isPending ? "Discarding…" : "Discard"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
