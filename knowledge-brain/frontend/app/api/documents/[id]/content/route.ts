import { BACKEND_URL } from "@/lib/config";
import { backendAuthHeaders } from "@/lib/auth";

// Same proxy reasoning as the upload/status routes — the browser never
// holds BACKEND_GATEWAY_SECRET. This one forwards the backend's response
// body directly (a PDF or a text file, not JSON), preserving its
// Content-Type and Content-Disposition headers so the browser renders it
// inline in the new tab the "View" link opens, instead of downloading it
// or guessing the wrong type (ADR-044).
export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  const response = await fetch(`${BACKEND_URL}/documents/${id}/content`, {
    headers: await backendAuthHeaders(),
    cache: "no-store",
  });

  const headers = new Headers();
  const contentType = response.headers.get("Content-Type");
  const contentDisposition = response.headers.get("Content-Disposition");
  if (contentType) headers.set("Content-Type", contentType);
  if (contentDisposition) headers.set("Content-Disposition", contentDisposition);

  return new Response(response.body, { status: response.status, headers });
}
