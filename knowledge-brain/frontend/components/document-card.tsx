import { FileText, ShieldAlert } from "lucide-react";

import type { DocumentListItem, DocumentStatus } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const STATUS_LABEL: Record<DocumentStatus, string> = {
  pending: "Pending",
  processing: "Processing",
  ready: "Ready",
  failed: "Failed",
  pending_review: "Needs review",
};

function StatusBadge({ status }: { status: DocumentStatus }) {
  if (status === "ready") {
    return <Badge>{STATUS_LABEL[status]}</Badge>;
  }
  if (status === "failed") {
    return <Badge variant="destructive">{STATUS_LABEL[status]}</Badge>;
  }
  if (status === "pending_review") {
    return (
      <Badge
        variant="outline"
        className="border-amber-600/30 bg-amber-500/10 text-amber-600 dark:text-amber-400"
      >
        {STATUS_LABEL[status]}
      </Badge>
    );
  }
  return <Badge variant="secondary">{STATUS_LABEL[status]}</Badge>;
}

function formatUploadedAt(uploadedAt: string) {
  return new Date(uploadedAt).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function DocumentCard({ document }: { document: DocumentListItem }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2">
            <FileText className="size-4 shrink-0 text-muted-foreground" />
            <CardTitle className="truncate text-sm">{document.filename}</CardTitle>
          </div>
          <StatusBadge status={document.status} />
        </div>
        {document.domains.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {document.domains.map((domain) => (
              <Badge key={domain} variant="outline" className="text-[0.65rem] font-normal">
                {domain}
              </Badge>
            ))}
          </div>
        )}
      </CardHeader>
      <CardContent className="flex items-center justify-between text-xs text-muted-foreground">
        <span>Uploaded {formatUploadedAt(document.uploaded_at)}</span>
        {document.pii_detected && (
          <span
            className={cn(
              "flex items-center gap-1 font-medium text-amber-600 dark:text-amber-400",
            )}
          >
            <ShieldAlert className="size-3.5" />
            PII detected
          </span>
        )}
      </CardContent>
    </Card>
  );
}
