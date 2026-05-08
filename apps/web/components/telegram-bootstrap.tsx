"use client";

import * as React from "react";

import { runBootstrapAuthSession } from "@/lib/auth/bootstrap-session";
import { refreshAccessToken } from "@/lib/auth/refresh-access";
import { startCloseQueueWatcher } from "@/lib/offline/close-queue";
import { startOfflineQueueWatcher } from "@/lib/offline/queue";
import { useAuthStore } from "@/lib/stores/auth-store";
import {
  subscribeTelegramExpandOnViewportChange,
  waitForTelegramWebApp,
} from "@/lib/telegram/init";

function isAccessTokenExpiringSoon(token: string | null): boolean {
  if (!token) return true;
  try {
    const parts = token.split(".");
    if (parts.length < 2 || !parts[1]) return true;
    const payload = JSON.parse(atob(parts[1])) as { exp?: number };
    return typeof payload.exp === "number" && Date.now() / 1000 > payload.exp - 60;
  } catch {
    return true;
  }
}

interface BootstrapProps {
  children: React.ReactNode;
}

/**
 * Boots the Telegram WebApp lifecycle and persists auth hydration.
 *
 * Delegates sequential work (SDK → persist → refresh/handshake → mark complete) to
 * `runBootstrapAuthSession` so Strict Mode duplicate effects await one shared pipeline.
 *
 * Splash / errors are rendered in `app/page.tsx`.
 *
 * Subscribes to `viewportChanged` (or `visualViewport` resize fallback) so we call
 * `expand()` again after iOS rotates / chrome height changes.
 */
export function TelegramBootstrap({ children }: BootstrapProps): React.JSX.Element {
  React.useEffect(() => {
    void runBootstrapAuthSession();
    const stopQueue = startOfflineQueueWatcher();
    const stopCloseQueue = startCloseQueueWatcher();

    let unsubViewport: (() => void) | undefined;
    void waitForTelegramWebApp({ timeoutMs: 12_000 }).then((tg) => {
      if (tg) {
        unsubViewport = subscribeTelegramExpandOnViewportChange(tg);
      }
    });

    const handleVisibilityChange = () => {
      if (document.visibilityState !== "visible") return;
      const token = useAuthStore.getState().accessToken;
      if (isAccessTokenExpiringSoon(token)) {
        void refreshAccessToken();
      }
    };
    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      stopQueue();
      stopCloseQueue();
      unsubViewport?.();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, []);

  return <>{children}</>;
}
