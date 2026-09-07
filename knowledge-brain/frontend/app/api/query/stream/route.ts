import { BACKEND_URL } from "@/lib/config";
import { backendAuthHeaders } from "@/lib/auth";

// Same proxy reasoning as this app's other /api routes (documents,
// conversations) — the browser never holds BACKEND_GATEWAY_SECRET.
// Unlike those routes, this one must not buffer the response into a
// parsed JSON object: the backend's body is piped through untouched,
// chunk by chunk, so the browser actually sees tokens arrive
// incrementally instead of only once the whole SSE stream had already
// finished inside this proxy (ADR-043). The backend's own Content-Type
// is forwarded as-is rather than hardcoded, since a request that fails
// before streaming even starts (a bad conversation_id, a 503) comes
// back as plain JSON, not SSE.
export async function POST(request: Request) {
  const body = await request.json();

  const response = await fetch(`${BACKEND_URL}/query/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await backendAuthHeaders()) },
    body: JSON.stringify(body),
  });

  const headers = new Headers();
  const contentType = response.headers.get("Content-Type");
  if (contentType) headers.set("Content-Type", contentType);
  headers.set("Cache-Control", "no-cache");
  headers.set("X-Accel-Buffering", "no");

  return new Response(response.body, { status: response.status, headers });
}
