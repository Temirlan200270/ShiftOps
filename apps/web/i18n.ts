import { getRequestConfig } from "next-intl/server";
import { cookies, headers } from "next/headers";

/**
 * next-intl request-time config — "no i18n routing" mode.
 *
 * Why no middleware:
 * - We're a Telegram Web App with a single-route shell (`app/page.tsx`) and
 *   state-driven sub-screens. URLs are never user-facing — Telegram opens
 *   the deep-link, Telegram's back button drives navigation. There's no
 *   reason to encode locale in the path.
 * - `next-intl@3.x` `createMiddleware` with `localePrefix: "never"` still
 *   requires `app/[locale]/...` directory structure under the hood, which
 *   we deliberately don't have. Hitting `/` without `[locale]` matched
 *   `/_not-found` in production (X-Matched-Path: /_not-found) — see the
 *   commit that removed `apps/web/middleware.ts`.
 *
 * Locale resolution priority:
 *   1. `NEXT_LOCALE` cookie (set by `LocaleSyncBoundary` after the Telegram
 *      `initDataUnsafe.user.language_code` lands on the client).
 *   2. `Accept-Language` header (first request, browser default).
 *   3. Hard fallback to `ru` (our pilot is Russian-speaking).
 */
const SUPPORTED_LOCALES = ["ru", "en"] as const;
type SupportedLocale = (typeof SUPPORTED_LOCALES)[number];

function isSupported(value: string | undefined): value is SupportedLocale {
  return value !== undefined && (SUPPORTED_LOCALES as readonly string[]).includes(value);
}

function detectLocale(): SupportedLocale {
  const cookieLocale = cookies().get("NEXT_LOCALE")?.value;
  if (isSupported(cookieLocale)) return cookieLocale;

  const acceptLanguage = headers().get("accept-language") ?? "";
  const primary = acceptLanguage.split(",")[0]?.split("-")[0]?.toLowerCase();
  if (isSupported(primary)) return primary;

  return "ru";
}

export default getRequestConfig(async () => {
  const locale = detectLocale();
  const mod = (await import(`./messages/${locale}.json`)) as {
    default: typeof import("./messages/ru.json");
  };
  return { messages: mod.default, locale };
});

export { SUPPORTED_LOCALES };
export type { SupportedLocale };
