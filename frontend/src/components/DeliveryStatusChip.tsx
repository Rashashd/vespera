import { Badge } from "@/components/ui/badge";

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
  // Delivery only begins once a report is approved. Until spec 13 wires the
  // real lifecycle (sent/delivered/delivery_failed via deliveryStatus), an
  // approved report sits at "approved_pending_delivery". Non-approved reports
  // have no delivery state yet, so the chip is hidden for them.
  const ds =
    deliveryStatus ?? (status === "approved" ? "approved_pending_delivery" : null);
  if (!ds) return null;

  return (
    <Badge variant={STATUS_VARIANT[ds] ?? "muted"}>
      {DELIVERY_LABEL[ds] ?? ds}
    </Badge>
  );
}
