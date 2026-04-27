/**
 * `NEXT_PUBLIC_API_URL` is embedded at build time. Set the Fly **origin**,
 * e.g. `https://shiftops-api.fly.dev` (no trailing slash) — we append `/api` so
 * that `fetch(\`\${base}/v1/...\`)` hits `/api/v1/...` (see `main.py` router).
 *
 * Local dev: unset → `/api` (same pattern). If you set the full value
 * `https://…/api` yourself, we do not double-append.
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
