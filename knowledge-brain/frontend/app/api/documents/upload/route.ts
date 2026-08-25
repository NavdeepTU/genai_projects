import { NextResponse } from "next/server";

import { BACKEND_GATEWAY_SECRET, BACKEND_URL, CURRENT_USER_ID } from "@/lib/config";

// Runs on the Next.js server, never in the browser — the only reason this
// file exists is so BACKEND_GATEWAY_SECRET never has to reach client-side
// JavaScript. The browser calls this same-origin route instead of the
// backend directly; this route then makes the real, secret-bearing call
// server-to-server.
export async function POST(request: Request) {
  const formData = await request.formData();

  const response = await fetch(`${BACKEND_URL}/documents/upload`, {
    method: "POST",
    headers: {
      "X-User-Id": CURRENT_USER_ID,
      "X-Gateway-Secret": BACKEND_GATEWAY_SECRET,
    },
    // Passing the FormData straight through preserves the file's bytes and
    // lets fetch set its own multipart Content-Type header (with the
    // correct boundary) — setting that header manually here would break it.
    body: formData,
  });

  const data = await response.json();
  return NextResponse.json(data, { status: response.status });
}
