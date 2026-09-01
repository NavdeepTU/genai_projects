import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { SESSION_COOKIE_NAME } from "@/lib/constants";

const PUBLIC_PATHS = new Set(["/login", "/signup"]);

// The cheap, first-line check: does a session cookie exist at all? This is
// deliberately *not* a real validity check — Proxy runs on every route,
// including prefetches, so Next.js's own guidance is to keep it to reading
// the cookie, never a database call. The real check — is this session
// actually still valid — happens where each page fetches its own data (see
// lib/api.ts and lib/auth.ts's getCurrentUser), the same two-layer shape
// user_id_middleware and require_admin already use on the backend.
export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (PUBLIC_PATHS.has(pathname)) {
    return NextResponse.next();
  }

  const hasSession = request.cookies.has(SESSION_COOKIE_NAME);
  if (!hasSession) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|.*\\.(?:svg|png|ico)$).*)"],
};
