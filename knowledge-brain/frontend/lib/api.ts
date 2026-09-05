// Types and client-safe calls only. The server-only calls (getDashboard,
// getAnalytics, getAdmin, getDocuments) live in lib/server-api.ts instead —
// splitting them out isn't just organization, it's required: those import
// lib/auth.ts, which imports next/headers, and next/headers can't be
// reached from a Client Component's bundle even indirectly. Keeping
// server-only code out of this file is what keeps query/page.tsx (a
// Client Component that imports postQuery from here) buildable at all.

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
  domains: string[];
};

export type DocumentUploadResponse = {
  id: string;
  filename: string;
  status: DocumentStatus;
  domains: string[];
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

export type DocumentListResponse = {
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
  conversation_id: string;
  correlation_id: string;
};

export type ConversationListItem = {
  id: string;
  title: string;
  updated_at: string;
};

export type ConversationListResponse = {
  conversations: ConversationListItem[];
  correlation_id: string;
};

export type Turn = {
  id: string;
  raw_question: string;
  answer: string;
  sources: QuerySource[];
  confidence: number | null;
  domains_used: string[];
  created_at: string;
};

export type ConversationDetailResponse = {
  id: string;
  title: string;
  turns: Turn[];
  correlation_id: string;
};

export type RecentQuery = {
  question: string;
  asked_at: string;
};

export type DashboardResponse = {
  document_count: number;
  recent_queries: RecentQuery[];
  correlation_id: string;
};

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

export type AdminAuditEntry = {
  timestamp: string;
  user_id: string | null;
  action: string;
  resource_type: string;
  resource_id: string;
};

export type DocumentPermissionEntry = {
  document_id: string;
  filename: string;
  user_id: string;
  granted_at: string;
};

export type AdminResponse = {
  audit_entries: AdminAuditEntry[];
  permissions: DocumentPermissionEntry[];
  correlation_id: string;
};

// Thrown by postQuery on a 401 instead of the generic Error below, so the
// calling Client Component can tell "you got logged out" apart from a
// real query failure and route you to /login with next/navigation's
// useRouter — this function itself isn't a component, so it can't call
// that hook directly.
export class UnauthorizedError extends Error {
  constructor() {
    super("Not logged in");
    this.name = "UnauthorizedError";
  }
}

// Called from the browser (a Client Component's submit handler), so this
// hits the same-origin Next.js proxy at /api/query, never the backend
// directly — the proxy is what attaches the session cookie and the
// gateway secret server-side. conversationId is omitted to start a new
// conversation; the response's own conversation_id is what the caller
// should send on every question after that.
export async function postQuery(question: string, conversationId: string | null): Promise<QueryResponse> {
  const response = await fetch("/api/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, conversation_id: conversationId }),
  });

  if (response.status === 401) {
    throw new UnauthorizedError();
  }

  const data = await response.json();
  if (!response.ok) {
    throw new Error(data?.detail ?? `Query failed (status ${response.status})`);
  }

  return data;
}
