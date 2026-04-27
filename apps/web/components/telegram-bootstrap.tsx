"use client";

import * as React from "react";

import { performHandshake } from "@/lib/auth/handshake";
import { startOfflineQueueWatcher } from "@/lib/offline/queue";
import { useAuthStore } from "@/lib/stores/auth-store";
import { getTelegramWebApp } from "@/lib/telegram/init";

interface BootstrapProps {
  children: React.ReactNode;
}

/**
 * Boots the Telegram WebApp lifecycle:
 *
 * 1. Calls `tg.ready()` so Telegram swaps the loading skeleton out.
 * 2. Calls `tg.expand()` to claim the full viewport (otherwise the app
 *    starts at ~50% screen height on iOS).
 * 3. If we don't have an `accessToken` yet, runs the initData handshake.
 *
 * Splash & error states are rendered by the page tree itself (driven off
 * `useAuthStore.me`); this component only orchestrates side-effects.
 */
export function TelegramBootstrap({ children }: BootstrapProps): React.JSX.Element {
  const me = useAuthStore((s) => s.me);

  React.useEffect(() => {
    const tg = getTelegramWebApp();
    if (tg) {
      try {
        tg.ready();
        tg.expand();
      } catch {
        // Telegram WebApp script may not be loaded in dev — ignore.
      }
    }
    if (!me) {
      void performHandshake().catch((err) => {
        const message = err instanceof Error ? err.message : "unknown";
        useAuthStore.getState().setHandshakeError(message);
      });
    }
    return startOfflineQueueWatcher();
  }, [me]);

  return <>{children}</>;
}
