import { useParams } from "react-router-dom";
import { useActingClient } from "@/auth/ActingClientContext";
import { ReportDetail } from "@/components/ReportDetail";
import { useAuth } from "@/auth/AuthContext";

interface Props {
  mode: "queue" | "all-reports" | "portal";
}

export default function ReportDetailPage({ mode }: Props) {
  const { reportId } = useParams<{ reportId: string }>();
  const { clientId: actingClientId } = useActingClient();
  const { user } = useAuth();

  // For portal mode, client-users use their own client_id
  const clientId =
    mode === "portal" && user?.user_type === "client"
      ? user.client_id ?? actingClientId
      : actingClientId;

  if (!reportId) {
    return <div className="p-8 text-destructive">Invalid report ID.</div>;
  }

  return (
    <div className="h-full -m-6">
      <ReportDetail clientId={clientId} reportId={parseInt(reportId, 10)} mode={mode} />
    </div>
  );
}
