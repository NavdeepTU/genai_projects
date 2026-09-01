import { NextResponse } from "next/server";

import { BACKEND_GATEWAY_SECRET, BACKEND_URL } from "@/lib/config";
import { SESSION_COOKIE_NAME, clearSessionCookie, getSessionToken } from "@/lib/auth";

// Same proxy reasoning as every other /api route. Ends the session on the
// backend (deletes the real Session row, not just the cookie), then clears
// this app's own cookie regardless of whether the backend call succeeded —
// logging out should never leave the browser holding onto a cookie.
export async function POST() {
  const token = await getSessionToken();

  if (token) {
    await fetch(`${BACKEND_URL}/auth/logout`, {
      method: "POST",
      headers: {
        Cookie: `${SESSION_COOKIE_NAME}=${token}`,
        "X-Gateway-Secret": BACKEND_GATEWAY_SECRET,
      },
    });
  }

  await clearSessionCookie();
  return NextResponse.json({ ok: true });
}
