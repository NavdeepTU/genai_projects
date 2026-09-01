import { NextResponse } from "next/server";

import { BACKEND_URL } from "@/lib/config";
import { backendAuthHeaders } from "@/lib/auth";

// Same proxy reasoning as the upload route: this keeps BACKEND_GATEWAY_SECRET
// server-side while the browser polls this same-origin path every couple of
// seconds to watch a document move through the pipeline.
export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  const response = await fetch(`${BACKEND_URL}/documents/${id}/status`, {
    headers: await backendAuthHeaders(),
    cache: "no-store",
  });

  const data = await response.json();
  return NextResponse.json(data, { status: response.status });
}
