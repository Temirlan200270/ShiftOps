"use client";

import type { TelegramWebApp } from "@/lib/telegram/init";
import { getTelegramWebApp } from "@/lib/telegram/init";

/**
 * True when Telegram exposes BiometricManager with authenticate — older clients
 * simply omit it (feature disabled).
 */
export function isShiftCloseBiometricSupported(): boolean {
  if (typeof window === "undefined") return false;
  const bm = getTelegramWebApp()?.BiometricManager;
  return typeof bm?.init === "function" && typeof bm?.authenticate === "function";
}

function biometricManager(): TelegramWebApp["BiometricManager"] | undefined {
  return getTelegramWebApp()?.BiometricManager;
}

/**
 * Optional FaceID / fingerprint before closing a shift. Not a legal signature.
 * Returns true when biometrics are unavailable (caller should skip when unsupported).
 */
export async function authenticateShiftClose(reason: string): Promise<boolean> {
  const bm = biometricManager();
  if (!bm?.init || !bm.authenticate) {
    return true;
  }

  const main = new Promise<boolean>((resolve) => {
    try {
      bm.init?.(() => {
        bm.authenticate?.({ reason }, (success) => {
          resolve(Boolean(success));
        });
      });
    } catch {
      resolve(false);
    }
  });

  const timeout = new Promise<boolean>((resolve) => {
    if (typeof window === "undefined") {
      resolve(false);
      return;
    }
    window.setTimeout(() => resolve(false), 25_000);
  });

  return Promise.race([main, timeout]);
}
