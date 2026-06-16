import { useEffect } from "react";
import { X } from "lucide-react";
import { Button } from "./button";

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: React.ReactNode;
}

/**
 * Lightweight modal dialog (overlay + centered card). Closes on overlay click and Escape.
 * Used for create/edit forms where the Radix alert-dialog (confirm-only) is too narrow.
 */
export function Modal({ open, onClose, title, description, children }: ModalProps) {
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/50 p-4 pt-20"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-lg border bg-card shadow-xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="flex items-start justify-between border-b px-5 py-4">
          <div className="space-y-1">
            <h2 className="text-base font-semibold">{title}</h2>
            {description && (
              <p className="text-xs text-muted-foreground">{description}</p>
            )}
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            aria-label="Close dialog"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}
