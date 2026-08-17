import { FileText, ShieldAlert } from "lucide-react";

import { getDocuments, type DocumentListItem, type DocumentStatus } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

// This page's data is inherently per-user and changes on every upload —
// without this, Next.js would treat it as eligible for static prerendering
// (no cookies/headers/searchParams used), fetch it once at build time in
// production, and serve that same frozen snapshot to everyone forever.
// Dev mode hides this entirely (pages always render fresh there), so this
// wouldn't have surfaced without checking the real caching docs.
export const dynamic = "force-dynamic";

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

function DocumentCard({ document }: { document: DocumentListItem }) {
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

function EmptyState() {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-2 py-24 text-center">
      <FileText className="size-8 text-muted-foreground" strokeWidth={1.5} />
      <p className="text-lg font-medium">No documents yet</p>
      <p className="text-sm text-muted-foreground">
        Once you upload a document, it will show up here with its processing status.
      </p>
    </div>
  );
}

export default async function DocumentsPage() {
  const documents = await getDocuments();

  return (
    <div className="mx-auto max-w-6xl px-4 py-10">
      <h1 className="mb-8 text-2xl font-semibold">Documents</h1>

      {documents.length === 0 ? (
        <EmptyState />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {documents.map((document) => (
            <DocumentCard key={document.id} document={document} />
          ))}
        </div>
      )}
    </div>
  );
}
