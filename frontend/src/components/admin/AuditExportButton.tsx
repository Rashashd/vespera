import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

/**
 * FR-037: staff-only audit export.
 * Disabled until the audit-export endpoint ships (forward dependency on a later spec).
 * Lights up with no UI restructuring when the endpoint is added.
 */
export function AuditExportButton() {
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
              aria-label="Export audit log (not yet available)"
            >
              <Download className="h-4 w-4 mr-1" />
              Export audit log
            </Button>
          </span>
        </TooltipTrigger>
        <TooltipContent>
          Audit export is not yet available — coming in a later release
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
