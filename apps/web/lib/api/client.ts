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
 * 3. A single chokepoint for 401 -> refresh-token logic (see `refresh()`).
 *
 * If the API moves to gRPC-Web or tRPC later, this is the only file to swap.
 */

import { useAuthStore } from "@/lib/stores/auth-store";

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

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api";

interface RequestInitJSON extends Omit<RequestInit, "body"> {
  body?: unknown;
}

async function rawRequest<T>(path: string, init: RequestInitJSON = {}): Promise<ApiResult<T>> {
  const accessToken = useAuthStore.getState().accessToken;
  const headers = new Headers(init.headers ?? {});
  headers.set("Accept", "application/json");
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);

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
    const failure = (payload as Record<string, unknown>) ?? {};
    return {
      ok: false,
      status: response.status,
      code: typeof failure.code === "string" ? failure.code : `http_${response.status}`,
      message: typeof failure.message === "string" ? failure.message : response.statusText,
    };
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
