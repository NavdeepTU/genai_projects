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

export type QuerySource = {
  document_id: string;
  filename: string;
  chunk_text: string;
};

export type QueryResponse = {
  answer: string;
  sources: QuerySource[];
  confidence: number | null;
  correlation_id: string;
};

// Called from the browser (a Client Component's submit handler), so this
// hits the same-origin Next.js proxy at /api/query, never the backend
// directly — the proxy is what attaches X-User-Id and the gateway secret
// server-side. Unlike getDocuments below, this can't take BACKEND_URL as
// a parameter, since a browser fetch to a different origin would need
// CORS the backend doesn't have configured.
export async function postQuery(question: string): Promise<QueryResponse> {
  const response = await fetch("/api/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });

  const data = await response.json();
  if (!response.ok) {
    throw new Error(data?.detail ?? `Query failed (status ${response.status})`);
  }

  return data;
}

export type RecentQuery = {
  question: string;
  asked_at: string;
};

export type DashboardResponse = {
  document_count: number;
  recent_queries: RecentQuery[];
  correlation_id: string;
};

export async function getDashboard(): Promise<DashboardResponse> {
  const response = await fetch(`${BACKEND_URL}/dashboard`, {
    headers: {
      "X-User-Id": CURRENT_USER_ID,
      "X-Gateway-Secret": BACKEND_GATEWAY_SECRET,
    },
  });

  if (!response.ok) {
    throw new Error(`Failed to load dashboard (status ${response.status})`);
  }

  return response.json();
}

export type QueryVolumePoint = {
  date: string;
  count: number;
};

export type TopQuestion = {
  question: string;
  count: number;
};

export type AnalyticsResponse = {
  query_volume: QueryVolumePoint[];
  top_questions: TopQuestion[];
  avg_response_time_ms: number | null;
  correlation_id: string;
};

export async function getAnalytics(): Promise<AnalyticsResponse> {
  const response = await fetch(`${BACKEND_URL}/analytics`, {
    headers: {
      "X-User-Id": CURRENT_USER_ID,
      "X-Gateway-Secret": BACKEND_GATEWAY_SECRET,
    },
  });

  if (!response.ok) {
    throw new Error(`Failed to load analytics (status ${response.status})`);
  }

  return response.json();
}

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
