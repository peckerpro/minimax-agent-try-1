import axios from "axios";

// Single axios instance configured for the local hello-agent backend.
// The Vite dev server proxies `/api` to http://127.0.0.1:8648; in
// production, the FastAPI StaticFiles mount serves the SPA at `/` and
// `/api/*` is served by the FastAPI routers on the same origin.
export const api = axios.create({
  baseURL: "/api",
  timeout: 60_000,
  headers: { "Content-Type": "application/json" },
});

export default api;