// Types and client-safe calls only. The server-only calls (getDashboard,
// getAnalytics, getAdmin, getDocuments) live in lib/server-api.ts instead —
// splitting them out isn't just organization, it's required: those import
// lib/auth.ts, which imports next/headers, and next/headers can't be
// reached from a Client Component's bundle even indirectly. Keeping
// server-only code out of this file is what keeps query/page.tsx (a
// Client Component that imports streamQuery from here) buildable at all.

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
  has_file: boolean;
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
  condensed_question: string;
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
  tenant_id: string | null;
  user_id: string | null;
  action: string;
  resource_type: string;
  resource_id: string;
};

export type AdminResponse = {
  audit_entries: AdminAuditEntry[];
  correlation_id: string;
};

export type Tenant = {
  id: string;
  name: string;
};

// Called from the Admin page's tenant-management section (a Client
// Component), so this hits the same-origin proxy at /api/admin/tenants,
// never the backend directly — same reasoning as every other
// client-triggered call in this file (ADR-046).
export async function createTenant(name: string): Promise<Tenant> {
  const response = await fetch("/api/admin/tenants", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });

  if (response.status === 401) {
    throw new UnauthorizedError();
  }

  if (!response.ok) {
    let detail = `Failed to register tenant (status ${response.status})`;
    try {
      const data = await response.json();
      detail = data?.detail ?? detail;
    } catch {
      // Body wasn't JSON either — the generic message above stands.
    }
    throw new Error(detail);
  }

  return response.json();
}

// Thrown by streamQuery on a 401, so the calling Client Component can
// tell "you got logged out" apart from a real query failure and route
// you to /login with next/navigation's useRouter — this function isn't
// a component, so it can't call that hook directly.
export class UnauthorizedError extends Error {
  constructor() {
    super("Not logged in");
    this.name = "UnauthorizedError";
  }
}

// One event from the backend's Server-Sent Events stream (ADR-043),
// already parsed out of its `event: ...\ndata: ...\n\n` wire format.
// `chunk`/`ttft`/`retract` only ever appear for a real, single-domain
// stream; a multi-domain question still sends its merged answer as one
// `chunk`, so the caller never needs to know which path produced it.
export type StreamEvent =
  | { type: "chunk"; text: string }
  | { type: "ttft"; ms: number }
  | { type: "retract"; reason: string }
  | {
      type: "done";
      answer: string;
      blocked: boolean;
      block_reason: string | null;
      sources: QuerySource[];
      confidence: number | null;
      domains_used: string[];
      partial: boolean;
      conversation_id: string;
      correlation_id: string;
    }
  | { type: "error"; detail: string };

function parseSseFrame(frame: string): StreamEvent | null {
  let eventType = "message";
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) eventType = line.slice("event:".length).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice("data:".length).trim());
  }
  if (dataLines.length === 0) return null;
  return { type: eventType, ...JSON.parse(dataLines.join("\n")) } as StreamEvent;
}

// Hits the same-origin Next.js proxy at /api/query/stream, never the
// backend directly — the proxy is what attaches the session cookie and
// the gateway secret server-side. Native EventSource can't send a POST
// body, so this reads the response as raw bytes and splits it into SSE
// frames by hand — the one piece of this feature genuinely new to the
// frontend (ADR-043).
export async function* streamQuery(
  question: string,
  conversationId: string | null,
): AsyncGenerator<StreamEvent> {
  const response = await fetch("/api/query/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, conversation_id: conversationId }),
  });

  if (response.status === 401) {
    throw new UnauthorizedError();
  }

  if (!response.ok || !response.body) {
    let detail = `Query failed (status ${response.status})`;
    try {
      const data = await response.json();
      detail = data?.detail ?? detail;
    } catch {
      // Body wasn't JSON either — the generic message above stands.
    }
    throw new Error(detail);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const event = parseSseFrame(buffer.slice(0, boundary));
      buffer = buffer.slice(boundary + 2);
      if (event) yield event;
      boundary = buffer.indexOf("\n\n");
    }
  }
}

// Called from the browser (the delete confirmation dialog), so this hits
// the same-origin proxy at /api/documents/{id}, never the backend
// directly — same reasoning as every other client-triggered call in this
// file (ADR-045).
export async function deleteDocument(documentId: string): Promise<void> {
  const response = await fetch(`/api/documents/${documentId}`, { method: "DELETE" });

  if (response.status === 401) {
    throw new UnauthorizedError();
  }

  if (!response.ok) {
    let detail = `Delete failed (status ${response.status})`;
    try {
      const data = await response.json();
      detail = data?.detail ?? detail;
    } catch {
      // Body wasn't JSON either — the generic message above stands.
    }
    throw new Error(detail);
  }
}
