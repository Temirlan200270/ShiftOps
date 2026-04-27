import type { AbstractIntlMessages } from "next-intl";
import { getRequestConfig } from "next-intl/server";

/**
 * next-intl request-time config. The middleware in `middleware.ts` resolves
 * the locale from cookies / accept-language; this hook turns it into the
 * messages bundle the React tree needs.
 *
 * Why locales in JSON, not YAML or Fluent: i18n keys are read by both Next
 * and ESLint plugins, and JSON has zero parser surprises across them.
 */
const SUPPORTED_LOCALES = ["ru", "en"] as const;
type SupportedLocale = (typeof SUPPORTED_LOCALES)[number];

function isSupported(value: string | undefined): value is SupportedLocale {
  return value !== undefined && (SUPPORTED_LOCALES as readonly string[]).includes(value);
}

export default getRequestConfig(async ({ locale }) => {
  const safeLocale: SupportedLocale = isSupported(locale) ? locale : "ru";
  const messages = (await import(`./messages/${safeLocale}.json`))
    .default as AbstractIntlMessages;
  return { messages, locale: safeLocale };
});

export { SUPPORTED_LOCALES };
export type { SupportedLocale };
