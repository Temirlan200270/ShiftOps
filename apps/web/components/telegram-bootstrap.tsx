"use client";

import * as React from "react";

import { runBootstrapAuthSession } from "@/lib/auth/bootstrap-session";
import { startOfflineQueueWatcher } from "@/lib/offline/queue";
import {
  subscribeTelegramExpandOnViewportChange,
  waitForTelegramWebApp,
} from "@/lib/telegram/init";

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

    let unsubViewport: (() => void) | undefined;
    void waitForTelegramWebApp({ timeoutMs: 12_000 }).then((tg) => {
      if (tg) {
        unsubViewport = subscribeTelegramExpandOnViewportChange(tg);
      }
    });

    return () => {
      stopQueue();
      unsubViewport?.();
    };
  }, []);

  return <>{children}</>;
}
