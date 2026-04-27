"use client";

import { get, set, del, keys } from "idb-keyval";

import { completeTask } from "@/lib/api/shifts";

/**
 * Offline-first photo upload queue.
 *
 * In bars Wi-Fi tends to die in the worst moment (e.g. while uploading
 * fridge-thermometer photos at the end of the shift). We store pending
 * uploads in IndexedDB so:
 *
 * 1. The UI never blocks the bartender — they can continue with the next
 *    task even if the previous one is still uploading.
 * 2. On window-focus / `online` event we drain the queue automatically.
 * 3. After a relog (browser restart inside Telegram) the queue survives.
 *
 * We deliberately keep this in plain `idb-keyval` instead of pulling in
 * Dexie or RxDB: a single keyset, no schema migrations, ~1KB of code.
 *
 * Workbox's BackgroundSync would be the "ideal" solution, but it requires a
 * full multipart `POST` payload to be replay-able from the SW context, which
 * is awkward when the JWT lives in JS memory (rotated every 15 min). Driving
 * the queue from the page (with TG WebApp's `online`/`focus` events) keeps
 * auth simple.
 */

const QUEUE_PREFIX = "shiftops.upload:";

interface QueuedUpload {
  id: string;
  taskId: string;
  comment: string;
  photo: Blob;
  enqueuedAt: number;
}

export async function enqueuePhotoUpload(input: {
  taskId: string;
  photo: Blob;
  comment?: string;
}): Promise<void> {
  const id = crypto.randomUUID();
  const entry: QueuedUpload = {
    id,
    taskId: input.taskId,
    comment: input.comment ?? "",
    photo: input.photo,
    enqueuedAt: Date.now(),
  };
  await set(`${QUEUE_PREFIX}${id}`, entry);
}

export async function drainQueue(): Promise<{ ok: number; failed: number }> {
  let ok = 0;
  let failed = 0;
  const allKeys = (await keys()) as string[];
  for (const key of allKeys) {
    if (!key.startsWith(QUEUE_PREFIX)) continue;
    const entry = (await get(key)) as QueuedUpload | undefined;
    if (!entry) {
      await del(key);
      continue;
    }
    const result = await completeTask({
      taskId: entry.taskId,
      comment: entry.comment || undefined,
      photo: entry.photo,
    });
    if (result.ok) {
      await del(key);
      ok += 1;
    } else if (result.status >= 400 && result.status < 500 && result.status !== 408) {
      // 4xx (other than timeout) means retrying won't help — drop the entry.
      await del(key);
      failed += 1;
    } else {
      // Network or 5xx — keep the entry for next attempt.
      failed += 1;
    }
  }
  return { ok, failed };
}

export function startOfflineQueueWatcher(): () => void {
  const drain = (): void => {
    void drainQueue();
  };
  window.addEventListener("online", drain);
  window.addEventListener("focus", drain);
  drain(); // run once on mount
  return () => {
    window.removeEventListener("online", drain);
    window.removeEventListener("focus", drain);
  };
}
