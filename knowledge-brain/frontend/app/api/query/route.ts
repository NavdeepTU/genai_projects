import { NextResponse } from "next/server";

import { BACKEND_URL } from "@/lib/config";
import { backendAuthHeaders } from "@/lib/auth";

// Same proxy reasoning as the document upload/status routes: the browser
// calls this same-origin path, which then makes the real, secret-bearing
// call to the backend server-to-server — BACKEND_GATEWAY_SECRET never
// reaches client-side JavaScript.
export async function POST(request: Request) {
  const body = await request.json();

  const response = await fetch(`${BACKEND_URL}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await backendAuthHeaders()) },
    body: JSON.stringify(body),
  });

  const data = await response.json();
  return NextResponse.json(data, { status: response.status });
}
