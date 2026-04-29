// Backend base URL.
//   Dev:  leave VITE_API_URL unset — Vite proxies /api to localhost:8001.
//   Prod: set VITE_API_URL in Vercel to the Railway service URL
//         (e.g. https://taxotrack-api.up.railway.app).
const RAW = import.meta.env.VITE_API_URL ?? "";
export const API_BASE = RAW.replace(/\/$/, "");

export const apiUrl = (path: string) =>
  `${API_BASE}${path.startsWith("/") ? path : `/${path}`}`;
