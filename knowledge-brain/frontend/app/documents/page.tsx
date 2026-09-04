import { FileText } from "lucide-react";

import { getDocuments } from "@/lib/server-api";
import { DocumentCard } from "@/components/document-card";
import { UploadDropzone } from "@/components/upload-dropzone";

// This page's data is inherently per-user and changes on every upload —
// without this, Next.js would treat it as eligible for static prerendering
// (no cookies/headers/searchParams used), fetch it once at build time in
// production, and serve that same frozen snapshot to everyone forever.
// Dev mode hides this entirely (pages always render fresh there), so this
// wouldn't have surfaced without checking the real caching docs.
export const dynamic = "force-dynamic";

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
      <h1 className="mb-6 text-2xl font-semibold">Documents</h1>

      <div className="mb-8">
        <UploadDropzone />
      </div>

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
