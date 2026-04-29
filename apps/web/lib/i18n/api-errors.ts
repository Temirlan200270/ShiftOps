import type { ApiFailure } from "@/lib/api/client";

type Translator = (key: string, values?: Record<string, unknown>) => string;

export function localiseApiFailure(
  failure: Pick<ApiFailure, "code" | "message" | "status">,
  tErr: Translator,
): string {
  switch (failure.code) {
    case "network":
      return tErr("network");
    case "privileged_rls_unavailable":
      return tErr("privilegedRlsUnavailable");
    case "missing_bearer_token":
    case "invalid_token":
    case "not_an_access_token":
      return tErr("sessionExpired");
    default:
      // Most endpoints keep `message` developer-oriented; prefer i18n.
      // If we don't recognise the code yet, fall back to the server message.
      return failure.message || tErr("generic");
  }
}

