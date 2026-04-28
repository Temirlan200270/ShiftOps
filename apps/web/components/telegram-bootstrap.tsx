"use client";

import * as React from "react";

import { HandshakeError, performHandshake } from "@/lib/auth/handshake";
import { refreshAccessToken } from "@/lib/auth/refresh-access";
import { startOfflineQueueWatcher } from "@/lib/offline/queue";
import { useAuthStore } from "@/lib/stores/auth-store";
import { waitForTelegramWebApp } from "@/lib/telegram/init";

interface BootstrapProps {
  children: React.ReactNode;
}

/**
 * Boots the Telegram WebApp lifecycle:
 * 1. Waits for the SDK to be ready.
 * 2. Calls ready/expand.
 * 3. Handles auth (refresh or handshake).
 */
export function TelegramBootstrap({ children }: BootstrapProps): React.JSX.Element {
  const isInitialized = React.useRef(false);

  React.useEffect(() => {
    if (isInitialized.current) return;
    isInitialized.current = true;

    let cancelled = false;

    async function runBootstrap(): Promise<void> {
      // 1. Ensure Telegram SDK is loaded (it's deferred in layout.tsx)
      const tg = await waitForTelegramWebApp();
      if (cancelled) return;

      if (tg) {
        try {
          tg.ready();
          tg.expand();
        } catch (err) {
          console.warn("Telegram SDK ready/expand failed", err);
        }
      }

      // 2. Perform Auth
      try {
        const state = useAuthStore.getState();
        
        // If we already have a session, just finish.
        if (state.accessToken && state.me) {
          return;
        }

        // If we have a refresh token, try that first.
        if (state.refreshToken) {
          const ok = await refreshAccessToken();
          if (cancelled) return;
          if (ok) return;
        }

        // Otherwise, full handshake.
        await performHandshake().catch((err) => {
          if (err instanceof HandshakeError) {
            useAuthStore.getState().setHandshakeError(err.message, err.code);
            return;
          }
          const message = err instanceof Error ? err.message : "unknown";
          useAuthStore.getState().setHandshakeError(message, null);
        });
      } finally {
        useAuthStore.getState().markAuthBootstrapComplete();
      }
    }

    const unsub =
      useAuthStore.persist.hasHydrated() !== true
        ? useAuthStore.persist.onFinishHydration(() => {
            if (!cancelled) void runBootstrap();
          })
        : () => {};

    if (useAuthStore.persist.hasHydrated() === true) {
      void runBootstrap();
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
