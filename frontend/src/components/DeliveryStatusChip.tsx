import { Badge } from "@/components/ui/badge";
import type { ReportSummary } from "@/api/schemas";

interface Props {
  status: string;
  deliveryStatus?: string;
}

const DELIVERY_LABEL: Record<string, string> = {
  approved_pending_delivery: "Approved (pending delivery)",
  sent: "Sent",
  delivered: "Delivered",
  delivery_failed: "Delivery failed",
};

const STATUS_VARIANT: Record<
  string,
  "default" | "secondary" | "destructive" | "outline" | "muted"
> = {
  approved_pending_delivery: "muted",
  sent: "secondary",
  delivered: "default",
  delivery_failed: "destructive",
};

export function DeliveryStatusChip({ status, deliveryStatus }: Props) {
  // Derive delivery_status when not provided (reviewer-facing)
  const ds =
    deliveryStatus ??
    (status === "approved" ? "approved_pending_delivery" : "approved_pending_delivery");

  return (
    <Badge variant={STATUS_VARIANT[ds] ?? "muted"}>
      {DELIVERY_LABEL[ds] ?? ds}
    </Badge>
  );
}
