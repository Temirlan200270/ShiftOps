"use client";

/**
 * Telegram WebApp bootstrap helpers.
 *
 * We deliberately wrap `@telegram-apps/sdk-react` lazily because:
 * 1. The SDK throws if instantiated outside a TWA host (e.g. local dev in a
 *    plain browser). We want a degraded "developer mode" instead of crashes.
 * 2. The SDK is heavy and we don't want it on the SSR critical path.
 *
 * `getInitDataRaw()` is what the back-end's `/api/v1/auth/exchange` expects.
 */

interface TelegramWebApp {
  initData: string;
  initDataUnsafe: { user?: { language_code?: string } };
  ready: () => void;
  expand: () => void;
  HapticFeedback?: {
    impactOccurred?: (style: "light" | "medium" | "heavy" | "rigid" | "soft") => void;
    notificationOccurred?: (style: "error" | "success" | "warning") => void;
  };
  themeParams?: Record<string, string>;
  colorScheme?: "light" | "dark";
  MainButton?: {
    show: () => void;
    hide: () => void;
    setText: (t: string) => void;
    onClick: (cb: () => void) => void;
    offClick: (cb: () => void) => void;
    enable: () => void;
    disable: () => void;
  };
}

declare global {
  interface Window {
    Telegram?: { WebApp: TelegramWebApp };
  }
}

export function getTelegramWebApp(): TelegramWebApp | null {
  if (typeof window === "undefined") return null;
  return window.Telegram?.WebApp ?? null;
}

export function getInitDataRaw(): string | null {
  return getTelegramWebApp()?.initData ?? null;
}

export function getTelegramLanguage(): "ru" | "en" {
  const lang = getTelegramWebApp()?.initDataUnsafe?.user?.language_code;
  return lang?.startsWith("ru") ? "ru" : "en";
}

export function haptic(style: "light" | "medium" | "heavy" = "light"): void {
  getTelegramWebApp()?.HapticFeedback?.impactOccurred?.(style);
}

export function notify(style: "success" | "warning" | "error"): void {
  getTelegramWebApp()?.HapticFeedback?.notificationOccurred?.(style);
}
