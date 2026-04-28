"use client";

import * as React from "react";

import { HandshakeError, performHandshake } from "@/lib/auth/handshake";
import { refreshAccessToken } from "@/lib/auth/refresh-access";
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
 * 3. After persisted state rehydrates: if there is no access token, tries
 *    refresh JWT first, then initData handshake.
 *
 * Splash & error states are rendered by `app/page.tsx` (driven off
 * `me` / `accessToken` / handshake error); this component only orchestrates
 * side-effects.
 */
export function TelegramBootstrap({ children }: BootstrapProps): React.JSX.Element {
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

    let cancelled = false;

    async function authenticateAfterHydrate(): Promise<void> {
      const state = useAuthStore.getState();
      if (state.accessToken) {
        return;
      }
      if (state.refreshToken) {
        const ok = await refreshAccessToken();
        if (cancelled) {
          return;
        }
        if (ok) {
          return;
        }
      }

      await performHandshake().catch((err) => {
        if (err instanceof HandshakeError) {
          useAuthStore.getState().setHandshakeError(err.message, err.code);
          return;
        }
        const message = err instanceof Error ? err.message : "unknown";
        useAuthStore.getState().setHandshakeError(message, null);
      });
    }

    const unsub = useAuthStore.persist.onFinishHydration(() => {
      if (!cancelled) {
        void authenticateAfterHydrate();
      }
    });

    if (useAuthStore.persist.hasHydrated()) {
      void authenticateAfterHydrate();
    }

    const stopQueue = startOfflineQueueWatcher();

    return () => {
      cancelled = true;
      unsub();
      stopQueue();
    };
  }, []);

  return <>{children}</>;
}
