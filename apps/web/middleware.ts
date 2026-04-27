import createMiddleware from "next-intl/middleware";

import { SUPPORTED_LOCALES } from "@/i18n";

/**
 * We do NOT prefix routes with `/ru` or `/en`. Telegram WebApp deep-links
 * always land on `/` and we want the user's last picked locale (cookie) or
 * the Telegram-provided `language_code` to drive selection — not the URL.
 *
 * `localePrefix: "never"` matches docs/AUTH_FLOW.md §3.
 */
export default createMiddleware({
  locales: [...SUPPORTED_LOCALES],
  defaultLocale: "ru",
  localePrefix: "never",
});

export const config = {
  matcher: ["/((?!_next|api|.*\\..*).*)"],
};
