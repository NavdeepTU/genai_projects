import { NextResponse } from "next/server";

import { BACKEND_URL } from "@/lib/config";
import { backendAuthHeaders } from "@/lib/auth";

// Same proxy reasoning as every other route here — the browser never
// holds BACKEND_GATEWAY_SECRET (ADR-048). The backend's own
// require_admin dependency is what actually enforces that only an admin
// can approve; this route just forwards the session cookie that lets
// the backend make that check.
export async function POST(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  const response = await fetch(`${BACKEND_URL}/admin/documents/${id}/approve`, {
    method: "POST",
    headers: await backendAuthHeaders(),
  });

  const data = await response.json();
  return NextResponse.json(data, { status: response.status });
}
