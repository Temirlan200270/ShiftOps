"use client";

import * as React from "react";

import { getTelegramWebApp } from "@/lib/telegram/init";
import type { ShiftSummary } from "@/lib/types";

/**
 * Muted palette aligned with globals.css HSL tokens — not full red for optional misses.
 * Only escalates header when critical tasks are still pending.
 */
const CHROME = {
  scheduled: { header: "#1e3a5f", background: "#121a28" },
  active: { header: "#243a63", background: "#0f1624" },
  activeCritical: { header: "#5c3d12", background: "#1a140e" },
} as const;

function resetNativeChrome(tg: NonNullable<ReturnType<typeof getTelegramWebApp>>): void {
  const p = tg.themeParams ?? {};
  try {
    if (typeof tg.setHeaderColor === "function") {
      tg.setHeaderColor(p.secondary_bg_color ?? "secondary_bg_color");
    }
    if (typeof tg.setBackgroundColor === "function") {
      tg.setBackgroundColor(p.bg_color ?? "bg_color");
    }
  } catch {
    /* ignore outside TWA */
  }
}

function applyChrome(
  tg: NonNullable<ReturnType<typeof getTelegramWebApp>>,
  header: string,
  background: string,
): void {
  try {
    tg.setHeaderColor?.(header);
    tg.setBackgroundColor?.(background);
  } catch {
    /* no-op */
  }
}

/**
 * Tints Telegram’s top bar / WebApp background from shift context. Resets when
 * the shift is idle, closed, or the user left the operator flow.
 */
export function useTelegramShiftChrome(input: {
  shift: ShiftSummary | null;
  surface: "dashboard" | "tasks" | "other";
}): void {
  const { shift, surface } = input;

  const criticalPending = React.useMemo(() => {
    if (!shift || shift.status !== "active") return 0;
    return shift.tasks.filter(
      (t) => t.criticality === "critical" && t.status === "pending",
    ).length;
  }, [shift]);

  React.useEffect(() => {
    const tg = getTelegramWebApp();
    if (!tg) return;

    if (!shift || surface === "other") {
      resetNativeChrome(tg);
      return;
    }

    const status = shift.status;
    if (status !== "active" && status !== "scheduled") {
      resetNativeChrome(tg);
      return;
    }

    if (status === "scheduled") {
      applyChrome(tg, CHROME.scheduled.header, CHROME.scheduled.background);
      return () => resetNativeChrome(tg);
    }

    if (criticalPending > 0) {
      applyChrome(tg, CHROME.activeCritical.header, CHROME.activeCritical.background);
    } else {
      applyChrome(tg, CHROME.active.header, CHROME.active.background);
    }

    return () => resetNativeChrome(tg);
  }, [shift, surface, criticalPending]);
}
