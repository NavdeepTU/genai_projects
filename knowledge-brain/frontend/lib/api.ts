import { BACKEND_GATEWAY_SECRET, BACKEND_URL, CURRENT_USER_ID } from "@/lib/config";

export type DocumentStatus = "pending" | "processing" | "ready" | "failed" | "pending_review";

export type ProcessingStage =
  | "queued"
  | "extracting"
  | "checking_pii"
  | "chunking"
  | "embedding"
  | "saving";

export type DocumentListItem = {
  id: string;
  filename: string;
  status: DocumentStatus;
  uploaded_at: string;
  pii_detected: boolean;
};

export type DocumentUploadResponse = {
  id: string;
  filename: string;
  status: DocumentStatus;
  correlation_id: string;
};

export type DocumentStatusResponse = {
  id: string;
  status: DocumentStatus;
  processing_stage: ProcessingStage;
  pii_detected: boolean;
  failure_reason: string | null;
  correlation_id: string;
};

type DocumentListResponse = {
  documents: DocumentListItem[];
  correlation_id: string;
};

export async function getDocuments(): Promise<DocumentListItem[]> {
  const response = await fetch(`${BACKEND_URL}/documents`, {
    headers: {
      "X-User-Id": CURRENT_USER_ID,
      "X-Gateway-Secret": BACKEND_GATEWAY_SECRET,
    },
  });

  if (!response.ok) {
    throw new Error(`Failed to load documents (status ${response.status})`);
  }

  const data: DocumentListResponse = await response.json();
  return data.documents;
}
