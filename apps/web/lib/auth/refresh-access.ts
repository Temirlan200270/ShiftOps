"use client";

/**
 * Exchange refresh JWT → new access JWT. Used on cold start when only refresh
 * is persisted, and inside `ApiClient` on 401.
 */

import { getNextPublicApiBase } from "@/lib/api/api-base";
import { useAuthStore } from "@/lib/stores/auth-store";

let refreshFlight: Promise<boolean> | null = null;

async function refreshAccessTokenOnce(): Promise<boolean> {
  const refreshToken = useAuthStore.getState().refreshToken;
  if (!refreshToken) {
    return false;
  }

  const API_BASE = getNextPublicApiBase();
  const response = await fetch(`${API_BASE}/v1/auth/refresh`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });

  const payload: unknown =
    response.headers.get("content-type")?.includes("application/json") === true
      ? await response.json().catch(() => ({}))
      : await response.text().catch(() => "");

  if (!response.ok) {
    return false;
  }

  const data = payload as { access_token?: string };
  if (typeof data.access_token !== "string") {
    return false;
  }

  useAuthStore.getState().setAccessToken(data.access_token);
  return true;
}

/** Serialized refresh so concurrent 401s only hit `/auth/refresh` once. */
export async function refreshAccessToken(): Promise<boolean> {
  if (refreshFlight) {
    return refreshFlight;
  }
  refreshFlight = refreshAccessTokenOnce().finally(() => {
    refreshFlight = null;
  });
  return refreshFlight;
}
