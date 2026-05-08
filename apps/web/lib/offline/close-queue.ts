"use client";

import { get, set, del, keys } from "idb-keyval";

import { closeShift } from "@/lib/api/shifts";
import { toast } from "@/lib/stores/toast-store";

/**
 * Offline-first shift-close queue.
 *
 * Mirrors the photo-upload queue (`queue.ts`) for the close-shift action.
 * When the operator taps "Закрыть смену" without connectivity the close
 * payload is persisted in IndexedDB.  On focus / `online` the queue drains
 * automatically — `closeShift` is retried with the same parameters.
 *
 * On successful drain a toast is shown; the shift will no longer appear in
 * `fetchMyShift()` on the next refresh.
 */

const CLOSE_QUEUE_PREFIX = "shiftops.close:";

interface QueuedClose {
  id: string;
  shiftId: string;
  confirmViolations: boolean;
  delayReason: string | null;
  violationReason: string | null;
  enqueuedAt: number;
}

let closeDrainFlight: Promise<{ ok: number; failed: number }> | null = null;

export async function enqueueShiftClose(input: {
  shiftId: string;
  confirmViolations: boolean;
  delayReason?: string | null;
  violationReason?: string | null;
}): Promise<void> {
  const id = crypto.randomUUID();
  const entry: QueuedClose = {
    id,
    shiftId: input.shiftId,
    confirmViolations: input.confirmViolations,
    delayReason: input.delayReason ?? null,
    violationReason: input.violationReason ?? null,
    enqueuedAt: Date.now(),
  };
  await set(`${CLOSE_QUEUE_PREFIX}${id}`, entry);
}

async function drainCloseQueueOnce(): Promise<{ ok: number; failed: number }> {
  let ok = 0;
  let failed = 0;
  const allKeys = (await keys()) as string[];
  for (const key of allKeys) {
    if (!key.startsWith(CLOSE_QUEUE_PREFIX)) continue;
    const entry = (await get(key)) as QueuedClose | undefined;
    if (!entry) {
      await del(key);
      continue;
    }
    const result = await closeShift({
      shiftId: entry.shiftId,
      confirmViolations: entry.confirmViolations,
      delayReason: entry.delayReason,
      violationReason: entry.violationReason,
    });
    if (result.ok) {
      await del(key);
      ok += 1;
      toast({
        variant: "success",
        title: "Смена закрыта",
        description: "Закрытие смены прошло успешно. Обновите экран, чтобы увидеть результат.",
      });
      // Dispatch a DOM event so any mounted listener (e.g. TaskListScreen)
      // can react by navigating to the summary screen.
      if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent("shiftclose:drained", { detail: { shiftId: entry.shiftId } }));
      }
    } else if (result.status === 401) {
      // Expired token — keep and retry after next token refresh.
      failed += 1;
    } else if (result.status >= 400 && result.status < 500 && result.status !== 408) {
      // 409 shift_not_active, 404 not found etc. — drop silently, no retry possible.
      await del(key);
      failed += 1;
    } else {
      // Network / 5xx — keep for next attempt.
      failed += 1;
    }
  }
  return { ok, failed };
}

export async function drainCloseQueue(): Promise<{ ok: number; failed: number }> {
  if (closeDrainFlight) {
    return closeDrainFlight;
  }
  closeDrainFlight = drainCloseQueueOnce().finally(() => {
    closeDrainFlight = null;
  });
  return closeDrainFlight;
}

export function startCloseQueueWatcher(): () => void {
  const debounceMs = 300;
  let timer: number | null = null;

  const drain = (): void => {
    if (timer) window.clearTimeout(timer);
    timer = window.setTimeout(() => {
      timer = null;
      void drainCloseQueue();
    }, debounceMs);
  };

  window.addEventListener("online", drain);
  window.addEventListener("focus", drain);
  drain(); // drain on mount in case there are pending entries

  return () => {
    window.removeEventListener("online", drain);
    window.removeEventListener("focus", drain);
    if (timer) window.clearTimeout(timer);
  };
}
