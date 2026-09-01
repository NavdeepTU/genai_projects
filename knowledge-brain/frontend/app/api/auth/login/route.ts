import { NextResponse } from "next/server";

import { BACKEND_GATEWAY_SECRET, BACKEND_URL } from "@/lib/config";
import { applySessionFromResponse } from "@/lib/auth";

// Same proxy reasoning as the other /api routes: the browser calls this
// same-origin path, which makes the real, secret-bearing call to the
// backend server-to-server. The one thing unique to this route: on
// success, it pulls the session token out of the backend's own
// Set-Cookie header and re-issues it as this app's own cookie (see
// lib/auth.ts's applySessionFromResponse) rather than relaying that
// header verbatim.
export async function POST(request: Request) {
  const body = await request.json();

  const backendResponse = await fetch(`${BACKEND_URL}/auth/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Gateway-Secret": BACKEND_GATEWAY_SECRET,
    },
    body: JSON.stringify(body),
  });

  const data = await backendResponse.json();
  if (!backendResponse.ok) {
    return NextResponse.json(data, { status: backendResponse.status });
  }

  // The backend responded success but somehow gave us no usable session —
  // that's not a successful login, and returning 200 here would send the
  // browser off believing it's logged in with no cookie to prove it.
  if (!(await applySessionFromResponse(backendResponse))) {
    return NextResponse.json(
      { detail: "Login succeeded but no session could be started. Please try again." },
      { status: 502 },
    );
  }

  return NextResponse.json(data);
}
