// The backend has no real authentication yet (build-order item 14) — it
// accepts any non-empty X-User-Id as a self-asserted identity. This stands
// in for "the logged-in user" everywhere the frontend calls the API, until
// real auth exists.
export const CURRENT_USER_ID = "dev-user";

export const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

// Matches whatever APIM_GATEWAY_SECRET is set to in the backend's own
// .env for local development. In Azure, API Management stamps this header
// on automatically; locally, nothing does it for us, so we send it
// ourselves — same reason the README's curl examples do.
export const BACKEND_GATEWAY_SECRET = process.env.BACKEND_GATEWAY_SECRET ?? "";
