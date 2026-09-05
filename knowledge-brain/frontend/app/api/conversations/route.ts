import { NextResponse } from "next/server";

import { BACKEND_URL } from "@/lib/config";
import { backendAuthHeaders } from "@/lib/auth";

// Same proxy reasoning as the documents list route: keeps
// BACKEND_GATEWAY_SECRET server-side while the sidebar fetches this
// same-origin path.
export async function GET() {
  const response = await fetch(`${BACKEND_URL}/conversations`, {
    headers: await backendAuthHeaders(),
    cache: "no-store",
  });

  const data = await response.json();
  return NextResponse.json(data, { status: response.status });
}
