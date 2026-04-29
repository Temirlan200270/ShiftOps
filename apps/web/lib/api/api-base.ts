/**
 * `NEXT_PUBLIC_API_URL` is embedded at build time. Set the Fly **origin**,
 * e.g. `https://shiftops-api.fly.dev` (no trailing slash) — we append `/api` so
 * that `fetch(\`\${base}/v1/...\`)` hits `/api/v1/...` (see `main.py` router).
 *
 * Local dev: **do not** leave this unset unless you add a reverse-proxy:
 * with the default `/api` base, the browser calls the **Next.js** origin
 * (`/api/v1/...`), which has no such routes → **404 Not Found** on screens
 * like opening hours. Use e.g. `http://localhost:8000` (see `.env.example`).
 *
 * If you set the full value `https://…/api` yourself, we do not double-append.
 */
export function getNextPublicApiBase(): string {
  const raw = process.env.NEXT_PUBLIC_API_URL?.trim();
  if (!raw) return "/api";
  const noSlash = raw.replace(/\/$/, "");
  if (noSlash.startsWith("http://") || noSlash.startsWith("https://")) {
    if (noSlash.endsWith("/api")) return noSlash;
    return `${noSlash}/api`;
  }
  return noSlash;
}
