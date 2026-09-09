import { NextResponse } from "next/server";

import { BACKEND_URL } from "@/lib/config";
import { backendAuthHeaders } from "@/lib/auth";

// Same proxy reasoning as every other route here — the browser never
// holds BACKEND_GATEWAY_SECRET. The backend's own require_admin dependency
// is what actually enforces that only an admin can create a domain; this
// route just forwards the session cookie that lets the backend make that
// check.
export async function POST(request: Request) {
  const body = await request.json();

  const response = await fetch(`${BACKEND_URL}/admin/domains`, {
    method: "POST",
    headers: { ...(await backendAuthHeaders()), "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  const data = await response.json();
  return NextResponse.json(data, { status: response.status });
}
