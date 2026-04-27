/**
 * `NEXT_PUBLIC_API_URL` is embedded at build time. In Vercel → Settings →
 * Environment Variables, set for **Production** (and Preview if needed) the
 * public Fly URL, e.g. `https://shiftops-api.fly.dev` (no trailing slash).
 *
 * A literally **empty** value in the dashboard is not `undefined`, so
 * `process.env.NEXT_PUBLIC_API_URL ?? "/api"` would keep `""` and the client
 * would call same-origin `/v1/...` on Vercel (404). We treat blank like unset.
 */
export function getNextPublicApiBase(): string {
  const raw = process.env.NEXT_PUBLIC_API_URL?.trim();
  if (raw) return raw.replace(/\/$/, "");
  return "/api";
}
