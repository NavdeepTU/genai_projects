import { NextResponse } from "next/server";

import { BACKEND_URL } from "@/lib/config";
import { backendAuthHeaders } from "@/lib/auth";

// Same proxy reasoning as the documents status route.
export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  const response = await fetch(`${BACKEND_URL}/conversations/${id}`, {
    headers: await backendAuthHeaders(),
    cache: "no-store",
  });

  const data = await response.json();
  return NextResponse.json(data, { status: response.status });
}
