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
  /** https://core.telegram.org/bots/webapps#events-available-for-web-apps */
  onEvent?: (eventType: string, handler: () => void) => void;
  offEvent?: (eventType: string, handler: () => void) => void;
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

/**
 * After rotation / Safari chrome / keyboard / safe-area changes the WebApp height updates.
 * A single `expand()` at cold start is not always enough on iOS; re-invoke behind a throttle.
 */
export function subscribeTelegramExpandOnViewportChange(tg: TelegramWebApp): () => void {
  const throttleMs = 400;
  let last = 0;
  const expand = (): void => {
    const now = Date.now();
    if (now - last < throttleMs) {
      return;
    }
    last = now;
    try {
      tg.expand();
    } catch {
      /* no-op outside Telegram host */
    }
  };

  const onViewportChanged = (): void => {
    expand();
  };

  if (typeof tg.onEvent === "function") {
    tg.onEvent("viewportChanged", onViewportChanged);
    return () => {
      tg.offEvent?.("viewportChanged", onViewportChanged);
    };
  }

  if (typeof window !== "undefined" && window.visualViewport) {
    const vv = window.visualViewport;
    vv.addEventListener("resize", onViewportChanged);
    return () => {
      vv.removeEventListener("resize", onViewportChanged);
    };
  }

  return () => {};
}

/** Poll until `telegram-web-app.js` defines `Telegram.WebApp` (defer script may load after React effects). */
export function waitForTelegramWebApp(
  opts: { timeoutMs?: number; intervalMs?: number } = {},
): Promise<TelegramWebApp | null> {
  if (typeof window === "undefined") {
    return Promise.resolve(null);
  }
  const timeoutMs = opts.timeoutMs ?? 10_000;
  const intervalMs = opts.intervalMs ?? 40;
  return new Promise((resolve) => {
    const tg = getTelegramWebApp();
    if (tg) {
      resolve(tg);
      return;
    }
    let elapsed = 0;
    const id = window.setInterval(() => {
      const next = getTelegramWebApp();
      elapsed += intervalMs;
      if (next) {
        window.clearInterval(id);
        resolve(next);
        return;
      }
      if (elapsed >= timeoutMs) {
        window.clearInterval(id);
        resolve(null);
      }
    }, intervalMs);
  });
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
