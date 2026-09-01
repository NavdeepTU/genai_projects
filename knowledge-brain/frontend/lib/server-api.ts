// Server-only backend calls — every one of these reads the session cookie
// via lib/auth.ts, which means every one of these can only ever be called
// from a Server Component or a Route Handler, never from a Client
// Component. Kept in a separate file from lib/api.ts specifically so a
// Client Component can import the client-safe parts of that file (like
// postQuery) without accidentally pulling next/headers into its bundle.
import { redirect } from "next/navigation";

import { BACKEND_URL } from "@/lib/config";
import { backendAuthHeaders } from "@/lib/auth";
import type {
  AdminResponse,
  AnalyticsResponse,
  DashboardResponse,
  DocumentListItem,
  DocumentListResponse,
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

export async function getDocuments(): Promise<DocumentListItem[]> {
  const response = await authenticatedFetch("/documents");

  if (!response.ok) {
    throw new Error(`Failed to load documents (status ${response.status})`);
  }

  const data: DocumentListResponse = await response.json();
  return data.documents;
}
