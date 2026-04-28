"use client";

let serverTimeOffsetMs = 0;

/**
 * Stores the best-effort offset between server and client clocks.
 *
 * We derive it from the HTTP `Date` header when present. It is intentionally
 * lightweight: good enough to correct minute-level drift inside a TWA without
 * adding extra endpoints.
 */
export function updateServerTimeOffsetFromResponse(response: Response): void {
  const header = response.headers.get("date");
  if (!header) return;
  const serverMs = Date.parse(header);
  if (!Number.isFinite(serverMs)) return;
  serverTimeOffsetMs = serverMs - Date.now();
}

export function getServerTimeOffsetMs(): number {
  return serverTimeOffsetMs;
}

/** A clock that approximates server time. */
export function nowServerMs(): number {
  return Date.now() + serverTimeOffsetMs;
}

