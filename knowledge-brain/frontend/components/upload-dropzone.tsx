"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, ShieldAlert, UploadCloud, XCircle } from "lucide-react";

import type { DocumentStatusResponse, DocumentUploadResponse, ProcessingStage } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { ProgressBar } from "@/components/progress-bar";
import { cn } from "@/lib/utils";

const ALLOWED_EXTENSIONS = [".pdf", ".txt"];
const POLL_INTERVAL_MS = 2000;
// How long a finished (ready/failed/pending_review) card stays visible
// before this component removes it and leaves the rest to the document
// list below, which has by then already been refreshed to include it.
const SETTLE_DELAY_MS = 1500;

const STAGE_ORDER: ProcessingStage[] = [
  "queued",
  "extracting",
  "checking_pii",
  "chunking",
  "embedding",
  "saving",
];

const STAGE_LABEL: Record<ProcessingStage, string> = {
  queued: "Queued",
  extracting: "Extracting text",
  checking_pii: "Checking for sensitive data",
  chunking: "Splitting into chunks",
  embedding: "Generating embeddings",
  saving: "Saving",
};

type UploadState =
  | { kind: "processing"; stage: ProcessingStage }
  | { kind: "ready" }
  | { kind: "pending_review" }
  | { kind: "failed"; reason: string | null }
  | { kind: "error"; message: string };

type InFlightUpload = {
  key: string;
  filename: string;
  documentId: string | null;
  state: UploadState;
};

function stageProgressPercent(stage: ProcessingStage): number {
  const index = STAGE_ORDER.indexOf(stage);
  return ((index + 1) / STAGE_ORDER.length) * 100;
}

function UploadCard({ upload }: { upload: InFlightUpload }) {
  const { state } = upload;

  return (
    <Card className="gap-2 px-4 py-3">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-xs font-medium">{upload.filename}</span>
        {state.kind === "ready" && <CheckCircle2 className="size-4 shrink-0 text-primary" />}
        {state.kind === "failed" && <XCircle className="size-4 shrink-0 text-destructive" />}
        {state.kind === "error" && <XCircle className="size-4 shrink-0 text-destructive" />}
        {state.kind === "pending_review" && (
          <ShieldAlert className="size-4 shrink-0 text-amber-600 dark:text-amber-400" />
        )}
      </div>

      {state.kind === "processing" && (
        <div className="flex flex-col gap-1.5">
          <ProgressBar percent={stageProgressPercent(state.stage)} />
          <span className="text-[0.65rem] text-muted-foreground">{STAGE_LABEL[state.stage]}</span>
        </div>
      )}

      {state.kind === "ready" && (
        <span className="text-[0.65rem] text-muted-foreground">Ready</span>
      )}

      {state.kind === "pending_review" && (
        <span className="text-[0.65rem] text-amber-600 dark:text-amber-400">
          Flagged for review — possible sensitive data found
        </span>
      )}

      {state.kind === "failed" && (
        <span className="text-[0.65rem] text-destructive">
          {state.reason ?? "Processing failed"}
        </span>
      )}

      {state.kind === "error" && (
        <span className="text-[0.65rem] text-destructive">{state.message}</span>
      )}
    </Card>
  );
}

export function UploadDropzone() {
  const router = useRouter();
  const [isDragging, setIsDragging] = useState(false);
  const [uploads, setUploads] = useState<InFlightUpload[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollTimers = useRef(new Map<string, ReturnType<typeof setInterval>>());

  useEffect(() => {
    const timers = pollTimers.current;
    return () => {
      for (const timer of timers.values()) {
        clearInterval(timer);
      }
    };
  }, []);

  const updateUpload = useCallback((key: string, state: UploadState) => {
    setUploads((current) => current.map((u) => (u.key === key ? { ...u, state } : u)));
  }, []);

  const settleAndRemove = useCallback((key: string) => {
    const timer = pollTimers.current.get(key);
    if (timer !== undefined) {
      clearInterval(timer);
      pollTimers.current.delete(key);
    }
    setTimeout(() => {
      setUploads((current) => current.filter((u) => u.key !== key));
    }, SETTLE_DELAY_MS);
    router.refresh();
  }, [router]);

  const pollStatus = useCallback(
    (key: string, documentId: string) => {
      const timer = setInterval(async () => {
        try {
          const response = await fetch(`/api/documents/${documentId}/status`, { cache: "no-store" });
          if (!response.ok) {
            throw new Error(`Status check failed (${response.status})`);
          }
          const data: DocumentStatusResponse = await response.json();

          if (data.status === "ready") {
            updateUpload(key, { kind: "ready" });
            settleAndRemove(key);
          } else if (data.status === "failed") {
            updateUpload(key, { kind: "failed", reason: data.failure_reason });
            settleAndRemove(key);
          } else if (data.status === "pending_review") {
            updateUpload(key, { kind: "pending_review" });
            settleAndRemove(key);
          } else {
            updateUpload(key, { kind: "processing", stage: data.processing_stage });
          }
        } catch {
          updateUpload(key, { kind: "error", message: "Lost connection while checking status" });
          settleAndRemove(key);
        }
      }, POLL_INTERVAL_MS);

      pollTimers.current.set(key, timer);
    },
    [settleAndRemove, updateUpload],
  );

  const uploadFile = useCallback(
    async (file: File) => {
      const key = `${file.name}-${Date.now()}-${Math.random()}`;
      const isAllowed = ALLOWED_EXTENSIONS.some((ext) => file.name.toLowerCase().endsWith(ext));

      if (!isAllowed) {
        setUploads((current) => [
          ...current,
          {
            key,
            filename: file.name,
            documentId: null,
            state: { kind: "error", message: "Only .pdf and .txt files are supported" },
          },
        ]);
        setTimeout(() => {
          setUploads((current) => current.filter((u) => u.key !== key));
        }, SETTLE_DELAY_MS * 2);
        return;
      }

      setUploads((current) => [
        ...current,
        { key, filename: file.name, documentId: null, state: { kind: "processing", stage: "queued" } },
      ]);

      try {
        const formData = new FormData();
        formData.append("file", file);

        const response = await fetch("/api/documents/upload", { method: "POST", body: formData });
        if (!response.ok) {
          const body = await response.json().catch(() => null);
          throw new Error(body?.detail ?? `Upload failed (${response.status})`);
        }

        const data: DocumentUploadResponse = await response.json();
        setUploads((current) =>
          current.map((u) => (u.key === key ? { ...u, documentId: data.id } : u)),
        );
        pollStatus(key, data.id);
      } catch (err) {
        updateUpload(key, {
          kind: "error",
          message: err instanceof Error ? err.message : "Upload failed",
        });
        settleAndRemove(key);
      }
    },
    [pollStatus, settleAndRemove, updateUpload],
  );

  const handleFiles = useCallback(
    (files: FileList | null) => {
      if (!files) return;
      for (const file of Array.from(files)) {
        void uploadFile(file);
      }
    },
    [uploadFile],
  );

  return (
    <div className="flex flex-col gap-3">
      <div
        role="button"
        tabIndex={0}
        onClick={() => fileInputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") fileInputRef.current?.click();
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setIsDragging(false);
          handleFiles(e.dataTransfer.files);
        }}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-4 py-10 text-center transition-colors",
          isDragging ? "border-primary bg-primary/5" : "border-border hover:bg-muted/40",
        )}
      >
        <UploadCloud className="size-6 text-muted-foreground" strokeWidth={1.5} />
        <p className="text-sm font-medium">Drag and drop a document, or click to browse</p>
        <p className="text-xs text-muted-foreground">Supports .pdf and .txt</p>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={ALLOWED_EXTENSIONS.join(",")}
          className="hidden"
          onChange={(e) => {
            handleFiles(e.target.files);
            e.target.value = "";
          }}
        />
      </div>

      {uploads.length > 0 && (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {uploads.map((upload) => (
            <UploadCard key={upload.key} upload={upload} />
          ))}
        </div>
      )}
    </div>
  );
}
