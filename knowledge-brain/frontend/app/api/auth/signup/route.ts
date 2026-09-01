import { NextResponse } from "next/server";

import { BACKEND_GATEWAY_SECRET, BACKEND_URL } from "@/lib/config";
import { applySessionFromResponse } from "@/lib/auth";

// Same proxy reasoning as every other /api route. The backend's /auth/signup
// only creates the account, deliberately not a session (see ADR-036) — this
// route chains a second, server-to-server call to /auth/login with the same
// credentials right after, so a new user lands logged in instead of having
// to fill the login form again immediately after the signup form.
export async function POST(request: Request) {
  const body = await request.json();

  const signupResponse = await fetch(`${BACKEND_URL}/auth/signup`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Gateway-Secret": BACKEND_GATEWAY_SECRET,
    },
    body: JSON.stringify(body),
  });

  const signupData = await signupResponse.json();
  if (!signupResponse.ok) {
    return NextResponse.json(signupData, { status: signupResponse.status });
  }

  const loginResponse = await fetch(`${BACKEND_URL}/auth/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Gateway-Secret": BACKEND_GATEWAY_SECRET,
    },
    body: JSON.stringify(body),
  });

  const loginData = await loginResponse.json();
  if (!loginResponse.ok) {
    // The account exists — this would only fail from something like the
    // backend going down between the two calls. Report it as a login
    // problem, not a signup problem, since the account really was created.
    return NextResponse.json(loginData, { status: loginResponse.status });
  }

  // Same reasoning as /api/auth/login: a 2xx here with no usable session
  // means the account exists but the browser still isn't logged in.
  if (!(await applySessionFromResponse(loginResponse))) {
    return NextResponse.json(
      { detail: "Account created, but no session could be started. Please log in." },
      { status: 502 },
    );
  }

  return NextResponse.json(loginData);
}
