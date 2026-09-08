// Server-only backend calls — every one of these reads the session cookie
// via lib/auth.ts, which means every one of these can only ever be called
// from a Server Component or a Route Handler, never from a Client
// Component. Kept in a separate file from lib/api.ts specifically so a
// Client Component can import the client-safe parts of that file (like
// streamQuery) without accidentally pulling next/headers into its bundle.
import { redirect } from "next/navigation";

import { BACKEND_URL } from "@/lib/config";
import { backendAuthHeaders } from "@/lib/auth";
import type {
  AdminResponse,
  AnalyticsResponse,
  ConversationDetailResponse,
  ConversationListItem,
  ConversationListResponse,
  DashboardResponse,
  DocumentListItem,
  DocumentListResponse,
  Tenant,
} from "@/lib/api";

// Every Server Component page in this app calls the backend the same way:
// forward whatever session cookie this request has, plus the gateway
// secret. A 401 means the session is missing or no longer valid — the
// real, database-backed check, not just "was a cookie sent" (that cheaper
// check already happened in proxy.ts) — so it sends the caller to /login
// instead of letting a page try to render with no real identity.
async function authenticatedFetch(path: string): Promise<Response> {
  const response = await fetch(`${BACKEND_URL}${path}`, {
    headers: await backendAuthHeaders(),
  });

  if (response.status === 401) {
    redirect("/login");
  }

  return response;
}

export async function getDashboard(): Promise<DashboardResponse> {
  const response = await authenticatedFetch("/dashboard");

  if (!response.ok) {
    throw new Error(`Failed to load dashboard (status ${response.status})`);
  }

  return response.json();
}

export async function getAnalytics(): Promise<AnalyticsResponse> {
  const response = await authenticatedFetch("/analytics");

  if (!response.ok) {
    throw new Error(`Failed to load analytics (status ${response.status})`);
  }

  return response.json();
}

export async function getAdmin(): Promise<AdminResponse> {
  const response = await authenticatedFetch("/admin");

  if (!response.ok) {
    if (response.status === 403) {
      throw new Error(
        "You don't have admin access — set is_admin to true on your account's row in the users table.",
      );
    }
    throw new Error(`Failed to load admin data (status ${response.status})`);
  }

  return response.json();
}

// Public on the backend (needed before a session exists — the signup
// picker), but still goes through the same server-to-server path as
// every other backend call, since APIM's gateway secret is required on
// every route regardless of auth (ADR-046). Not run through
// authenticatedFetch: a missing/expired session here is normal, not a
// reason to redirect anyone to /login.
export async function getTenants(): Promise<Tenant[]> {
  const response = await fetch(`${BACKEND_URL}/tenants`, {
    headers: await backendAuthHeaders(),
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(`Failed to load tenants (status ${response.status})`);
  }

  const data: { tenants: Tenant[] } = await response.json();
  return data.tenants;
}

export async function getDocuments(): Promise<DocumentListItem[]> {
  const response = await authenticatedFetch("/documents");

  if (!response.ok) {
    throw new Error(`Failed to load documents (status ${response.status})`);
  }

  const data: DocumentListResponse = await response.json();
  return data.documents;
}

export async function getConversations(): Promise<ConversationListItem[]> {
  const response = await authenticatedFetch("/conversations");

  if (!response.ok) {
    throw new Error(`Failed to load conversations (status ${response.status})`);
  }

  const data: ConversationListResponse = await response.json();
  return data.conversations;
}

// Returns null for a 404 specifically (doesn't exist, or belongs to
// someone else — the backend doesn't distinguish the two) so the page
// can render a real "not found" state instead of the generic error
// boundary; any other failure still throws.
export async function getConversation(id: string): Promise<ConversationDetailResponse | null> {
  const response = await authenticatedFetch(`/conversations/${id}`);

  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`Failed to load conversation (status ${response.status})`);
  }

  return response.json();
}
