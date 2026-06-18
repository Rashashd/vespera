import { useState } from "react";
import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";

const BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) || "http://localhost:8000";

/**
 * FR-018: staff-only audit export. The backend role-scopes the result automatically
 * (manager → all events; admin → client/watchlist-management only).
 */
export function AuditExportButton({ clientId }: { clientId?: number | null }) {
  const [busy, setBusy] = useState(false);

  async function handleExport() {
    setBusy(true);
    try {
      const token = localStorage.getItem("pantera_token");
      const qs = clientId != null ? `&client_id=${clientId}` : "";
      const resp = await fetch(`${BASE_URL}/audit/export?format=csv${qs}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!resp.ok) throw new Error(`Export failed (HTTP ${resp.status})`);
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "audit-export.csv";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Button
      variant="outline"
      size="sm"
      onClick={handleExport}
      disabled={busy}
      aria-label="Export audit log"
    >
      <Download className="h-4 w-4 mr-1" />
      {busy ? "Exporting…" : "Export audit log"}
    </Button>
  );
}
