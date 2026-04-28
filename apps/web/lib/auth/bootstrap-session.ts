"use client";

/**
 * Single-flight post-hydration auth pipeline shared by TelegramBootstrap (and Strict Mode re-mounts).
 *
 * Order matters for TWA:
 * 1. Wait until `telegram-web-app.js` defined `Telegram.WebApp`.
 * 2. `tg.ready()` / `tg.expand()`.
 * 3. Wait for Zustand persist to rehydrate from storage (otherwise refreshToken/me are stale defaults).
 * 4. Refresh JWT or Telegram initData handshake.
 *
 * `performHandshake` and `refreshAccessToken` have their own in-flight guards; this module avoids duplicate
 * *pipelines* when React mounts the bootstrap effect twice in dev Strict Mode.
 */

import { HandshakeError, performHandshake } from "@/lib/auth/handshake";
import { refreshAccessToken } from "@/lib/auth/refresh-access";
import { useAuthStore } from "@/lib/stores/auth-store";
import { waitForTelegramWebApp } from "@/lib/telegram/init";

let bootstrapFlight: Promise<void> | null = null;

async function waitForPersistHydrated(): Promise<void> {
  if (useAuthStore.persist.hasHydrated()) {
    return;
  }
  await new Promise<void>((resolve) => {
    const unsub = useAuthStore.persist.onFinishHydration(() => {
      unsub();
      resolve();
    });
  });
}

/** Idempotent warm-up: callers await the same Promise while a bootstrap is in flight. */
export async function runBootstrapAuthSession(): Promise<void> {
  if (bootstrapFlight) {
    return bootstrapFlight;
  }

  bootstrapFlight = (async () => {
    const tg = await waitForTelegramWebApp({ timeoutMs: 12_000 });
    if (tg) {
      try {
        tg.ready();
        tg.expand();
      } catch {
        /* dev browser / Telegram not injecting WebApp */
      }
    }

    await waitForPersistHydrated();

    try {
      const state = useAuthStore.getState();

      if (state.accessToken && state.me) {
        return;
      }

      if (state.refreshToken) {
        const ok = await refreshAccessToken();
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
    } catch (err) {
      const message = err instanceof Error ? err.message : "bootstrap_failed";
      useAuthStore.getState().setHandshakeError(message, "bootstrap_exception");
    } finally {
      useAuthStore.getState().markAuthBootstrapComplete();
    }
  })().finally(() => {
    bootstrapFlight = null;
  });

  return bootstrapFlight;
}
