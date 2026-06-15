import { Download } from "lucide-react";
import { Button } from "./ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "./ui/tooltip";

/** FR-036: disabled until the delivery-layer export endpoint ships (forward dependency). */
export function DownloadReportButton() {
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
              aria-label="Download report (not yet available)"
            >
              <Download className="h-4 w-4 mr-1" />
              Export
            </Button>
          </span>
        </TooltipTrigger>
        <TooltipContent>
          Available once the delivery layer ships
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
