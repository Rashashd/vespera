import { useState } from "react";
import { Download } from "lucide-react";
import { Button } from "./ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "./ui/tooltip";

const BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) || "http://localhost:8000";

// The delivered artifact only exists from approval onward (spec 13 FR-017).
const DOWNLOADABLE = new Set(["approved", "sent", "delivered"]);

interface Props {
  clientId: number;
  reportId: number;
  status: string;
}

/** FR-017: download the rendered report document (the same artifact delivered to the client). */
export function DownloadReportButton({ clientId, reportId, status }: Props) {
  const [busy, setBusy] = useState(false);
  const downloadable = DOWNLOADABLE.has(status);

  async function handleDownload() {
    setBusy(true);
    try {
      const token = localStorage.getItem("pantera_token");
      const resp = await fetch(
        `${BASE_URL}/clients/${clientId}/reports/${reportId}/download`,
        { headers: token ? { Authorization: `Bearer ${token}` } : {} },
      );
      if (!resp.ok) throw new Error(`Download failed (HTTP ${resp.status})`);
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `report-${reportId}.html`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } finally {
      setBusy(false);
    }
  }

  if (!downloadable) {
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <span tabIndex={0}>
              <Button
                variant="outline"
                size="sm"
                disabled
                aria-disabled="true"
                aria-label="Download report (available after approval)"
              >
                <Download className="h-4 w-4 mr-1" />
                Export
              </Button>
            </span>
          </TooltipTrigger>
          <TooltipContent>Available once the report is approved</TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  return (
    <Button
      variant="outline"
      size="sm"
      onClick={handleDownload}
      disabled={busy}
      aria-label="Download report"
    >
      <Download className="h-4 w-4 mr-1" />
      {busy ? "Exporting…" : "Export"}
    </Button>
  );
}
