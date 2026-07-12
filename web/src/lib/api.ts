/**
 * Central API configuration.
 *
 * Set NEXT_PUBLIC_API_URL in your Vercel environment variables to point to
 * your Render backend (e.g., https://apexhft-api.onrender.com).
 * Falls back to localhost for local development.
 */
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// For WebSockets: swap http(s) -> ws(s) automatically
const WS_BASE = API_BASE.replace(/^https/, "wss").replace(/^http/, "ws");

export { API_BASE, WS_BASE };
