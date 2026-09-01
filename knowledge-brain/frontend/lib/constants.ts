// Dependency-free on purpose — this is the one place SESSION_COOKIE_NAME is
// actually defined. proxy.ts imports it directly from here (it can't import
// lib/auth.ts, which pulls in next/headers and the gateway secret); lib/auth.ts
// re-exports it so every existing `from "@/lib/auth"` import keeps working.
// Keeping both in sync this way means a rename can't silently drift between
// the edge-level check and the real one.
export const SESSION_COOKIE_NAME = "session_token";
