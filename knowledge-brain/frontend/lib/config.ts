export const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

// Matches whatever APIM_GATEWAY_SECRET is set to in the backend's own
// .env for local development. In Azure, API Management stamps this header
// on automatically; locally, nothing does it for us, so we send it
// ourselves — same reason the README's curl examples do.
export const BACKEND_GATEWAY_SECRET = process.env.BACKEND_GATEWAY_SECRET ?? "";
