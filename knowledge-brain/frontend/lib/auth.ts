import { cache } from "react";
import { cookies } from "next/headers";

import { BACKEND_GATEWAY_SECRET, BACKEND_URL } from "@/lib/config";
import { SESSION_COOKIE_NAME } from "@/lib/constants";

// Only ever import this file from a Server Component or a Route Handler —
// cookies() throws outside a request context, and nothing here is safe to
// ship to the browser anyway (it talks to the backend with the gateway
// secret).
export { SESSION_COOKIE_NAME };

// Matches the backend's own SESSION_LIFETIME (app/models/session.py) — the
// browser's copy of this cookie shouldn't outlive the session row it
// stands for.
const SESSION_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 7;

export type CurrentUser = {
  id: string;
  email: string;
  is_admin: boolean;
};

// Issues this app's own cookie, scoped to this app's own origin — not a
// byte-for-byte relay of the backend's Set-Cookie header. That header was
// shaped for a server-to-server response and carries no meaningful Domain
// of its own; a fresh cookie, with attributes that make sense for this
// app's environment, is the more correct move, not just a simpler one.
export async function setSessionCookie(token: string) {
  const cookieStore = await cookies();
  cookieStore.set(SESSION_COOKIE_NAME, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    maxAge: SESSION_COOKIE_MAX_AGE_SECONDS,
    path: "/",
  });
}

export async function clearSessionCookie() {
  const cookieStore = await cookies();
  cookieStore.delete(SESSION_COOKIE_NAME);
}

export async function getSessionToken(): Promise<string | undefined> {
  const cookieStore = await cookies();
  return cookieStore.get(SESSION_COOKIE_NAME)?.value;
}

// The headers every server-to-server call to the backend needs: the
// caller's session (if any) and the gateway secret. One shared builder
// instead of four separate copies of this same object literal — a future
// header this project's own enterprise requirements call for (e.g. a
// correlation id) only needs adding here once.
export async function backendAuthHeaders(): Promise<Record<string, string>> {
  const token = await getSessionToken();
  return {
    ...(token ? { Cookie: `${SESSION_COOKIE_NAME}=${token}` } : {}),
    "X-Gateway-Secret": BACKEND_GATEWAY_SECRET,
  };
}

// Pulls the session token out of a backend response's own Set-Cookie
// header and re-issues it as this app's own cookie. Returns false (instead
// of silently doing nothing) if the backend responded 2xx but somehow
// didn't include a usable Set-Cookie — a route handler calling this should
// treat that as a real failure, not a successful login with no session.
export async function applySessionFromResponse(response: Response): Promise<boolean> {
  const setCookieHeader = response.headers.get("set-cookie");
  const token = setCookieHeader?.match(new RegExp(`${SESSION_COOKIE_NAME}=([^;]+)`))?.[1];
  if (!token) return false;

  await setSessionCookie(token);
  return true;
}

// Asks the backend who this session actually belongs to — the real,
// database-backed check, not just "is a cookie present" (that cheaper
// check is what proxy.ts does, on every route, before this ever runs).
// Wrapped in React's cache() so a layout and a page both asking this
// during the same render only pay for one real network call.
export const getCurrentUser = cache(async (): Promise<CurrentUser | null> => {
  const token = await getSessionToken();
  if (!token) return null;

  const response = await fetch(`${BACKEND_URL}/auth/me`, {
    headers: await backendAuthHeaders(),
    cache: "no-store",
  });

  if (!response.ok) return null;
  return response.json();
});
