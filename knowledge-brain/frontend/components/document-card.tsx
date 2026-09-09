import { ExternalLink, FileText, ShieldAlert } from "lucide-react";

import type { DocumentListItem, DocumentStatus } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DeleteDocumentButton } from "@/components/delete-document-button";
import { SubmitForReviewButton } from "@/components/submit-for-review-button";
import { cn } from "@/lib/utils";

const STATUS_LABEL: Record<DocumentStatus, string> = {
  pending: "Pending",
  processing: "Processing",
  ready: "Ready",
  failed: "Failed",
  pending_review: "Needs review",
  in_review: "In review",
  rejected: "Rejected",
};

function StatusBadge({ status }: { status: DocumentStatus }) {
  if (status === "ready") {
    return <Badge>{STATUS_LABEL[status]}</Badge>;
  }
  if (status === "failed" || status === "rejected") {
    return <Badge variant="destructive">{STATUS_LABEL[status]}</Badge>;
  }
  if (status === "pending_review" || status === "in_review") {
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
        <div className="flex min-w-0 items-start justify-between gap-2">
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <FileText className="size-4 shrink-0 text-muted-foreground" />
            <CardTitle className="truncate text-sm">{document.filename}</CardTitle>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <StatusBadge status={document.status} />
            <DeleteDocumentButton documentId={document.id} filename={document.filename} />
          </div>
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
      <CardContent className="flex flex-col gap-2">
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>Uploaded {formatUploadedAt(document.uploaded_at)}</span>
          <div className="flex items-center gap-3">
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
            {document.has_file ? (
              <a
                href={`/api/documents/${document.id}/content`}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1 font-medium text-primary hover:underline"
              >
                <ExternalLink className="size-3.5" />
                View
              </a>
            ) : (
              <span className="text-muted-foreground/60">Not viewable</span>
            )}
          </div>
        </div>
        {document.status === "pending_review" && (
          <div className="flex items-center justify-between gap-2 rounded-md border border-amber-600/20 bg-amber-500/5 px-2.5 py-2 text-xs text-amber-700 dark:text-amber-400">
            <span>This document contains possible PII — review it, then send it for approval.</span>
            <SubmitForReviewButton documentId={document.id} />
          </div>
        )}
        {document.status === "in_review" && (
          <p className="text-xs text-muted-foreground">Awaiting an admin&apos;s decision.</p>
        )}
        {document.status === "rejected" && (
          <p className="text-xs text-destructive">
            Rejected by an admin — this document was never added to the knowledge base.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
