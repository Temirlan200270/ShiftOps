"use client";

/**
 * Tiny typed API client around fetch.
 *
 * Why DIY (per project rules): we have a small set of endpoints, full TS
 * inference, no need for a heavy SDK. The wrapper centralises:
 *
 * 1. Bearer token injection (read from `useAuthStore`).
 * 2. JSON parse + error normalisation into a `Result`-like discriminator
 *    so screens never have to try/catch a network call themselves.
 * 3. 401 → refresh access token via `/v1/auth/refresh` (single-flight), then one retry.
 */

import { refreshAccessToken } from "@/lib/auth/refresh-access";
import { useAuthStore } from "@/lib/stores/auth-store";

import { getNextPublicApiBase } from "./api-base";

export interface ApiSuccess<T> {
  ok: true;
  status: number;
  data: T;
}

export interface ApiFailure {
  ok: false;
  status: number;
  code: string;
  message: string;
}

export type ApiResult<T> = ApiSuccess<T> | ApiFailure;

const API_BASE = getNextPublicApiBase();

interface RequestInitJSON extends Omit<RequestInit, "body"> {
  body?: unknown;
}

function parseErrorPayload(payload: unknown): { code: string; message: string } {
  const record = (payload as Record<string, unknown>) ?? {};
  const code = typeof record.code === "string" ? record.code : "";
  const message = typeof record.message === "string" ? record.message : "";
  return { code, message };
}

function buildFailure(
  status: number,
  payload: unknown,
  fallbackMessage: string,
): ApiFailure {
  const { code, message } = parseErrorPayload(payload);
  return {
    ok: false,
    status,
    code: code || `http_${status}`,
    message: message || fallbackMessage,
  };
}

function shouldRetryAfterRefresh(status: number, failure: ApiFailure): boolean {
  if (status !== 401) {
    return false;
  }
  if (failure.code === "invalid_token") {
    return true;
  }
  if (failure.code === "not_an_access_token") {
    return true;
  }
  if (failure.code === "missing_bearer_token") {
    return true;
  }
  if (/signature has expired/i.test(failure.message)) {
    return true;
  }
  return false;
}

function logApiClientEvent(kind: string, meta: Record<string, unknown>): void {
  if (process.env.NODE_ENV !== "development") {
    return;
  }
  console.error("[api]", kind, meta);
}

async function rawRequest<T>(
  path: string,
  init: RequestInitJSON = {},
  options: { isRetryAfterRefresh?: boolean } = {},
): Promise<ApiResult<T>> {
  const skipRefresh =
    path.startsWith("/v1/auth/exchange") || path.startsWith("/v1/auth/refresh");

  const boot = useAuthStore.getState();
  if (!boot.accessToken && boot.refreshToken && !skipRefresh) {
    await refreshAccessToken();
  }

  const accessToken = useAuthStore.getState().accessToken;
  const headers = new Headers(init.headers ?? {});
  headers.set("Accept", "application/json");
  if (accessToken) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }

  let body: BodyInit | undefined;
  if (init.body instanceof FormData) {
    body = init.body;
  } else if (init.body !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(init.body);
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers, body });
  } catch (err) {
    logApiClientEvent("network_error", {
      path,
      method: init.method ?? "GET",
      message: err instanceof Error ? err.message : String(err),
    });
    return {
      ok: false,
      status: 0,
      code: "network",
      message: err instanceof Error ? err.message : "network error",
    };
  }

  if (response.status === 204) {
    return { ok: true, status: 204, data: undefined as unknown as T };
  }

  const contentType = response.headers.get("content-type") ?? "";
  const payload: unknown = contentType.includes("application/json")
    ? await response.json().catch(() => ({}))
    : await response.text().catch(() => "");

  if (!response.ok) {
    const failure = buildFailure(
      response.status,
      payload,
      typeof payload === "string" && payload.length > 0 ? payload : response.statusText,
    );

    if (
      !options.isRetryAfterRefresh &&
      !skipRefresh &&
      shouldRetryAfterRefresh(response.status, failure)
    ) {
      const refreshed = await refreshAccessToken();
      if (refreshed) {
        return rawRequest<T>(path, init, { isRetryAfterRefresh: true });
      }
    }

    logApiClientEvent("http_error", {
      path,
      method: init.method ?? "GET",
      status: response.status,
      code: failure.code,
    });
    return failure;
  }

  return { ok: true, status: response.status, data: payload as T };
}

export const api = {
  get: <T>(path: string) => rawRequest<T>(path, { method: "GET" }),
  post: <T>(path: string, body?: unknown) => rawRequest<T>(path, { method: "POST", body }),
  put: <T>(path: string, body?: unknown) => rawRequest<T>(path, { method: "PUT", body }),
  patch: <T>(path: string, body?: unknown) => rawRequest<T>(path, { method: "PATCH", body }),
  delete: <T>(path: string) => rawRequest<T>(path, { method: "DELETE" }),
  postForm: <T>(path: string, form: FormData) =>
    rawRequest<T>(path, { method: "POST", body: form }),
};
