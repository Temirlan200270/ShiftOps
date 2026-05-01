"use client";

import { getTelegramWebApp } from "@/lib/telegram/init";

const PREFIX = "shiftops:v1:";

export function taskCommentDraftKey(taskId: string): string {
  return `${PREFIX}task:${taskId}:comment`;
}

export function taskWaiverDraftKey(taskId: string): string {
  return `${PREFIX}task:${taskId}:waiver`;
}

export function isCloudStorageAvailable(): boolean {
  const cs = getTelegramWebApp()?.CloudStorage;
  return typeof cs?.setItem === "function" && typeof cs?.getItem === "function";
}

export async function cloudStorageGet(key: string): Promise<string | null> {
  const cs = getTelegramWebApp()?.CloudStorage;
  if (!cs?.getItem) return null;
  return new Promise((resolve) => {
    try {
      cs.getItem?.(key, (err, value) => {
        if (err != null) resolve(null);
        else resolve(value ?? null);
      });
    } catch {
      resolve(null);
    }
  });
}

export async function cloudStorageSet(key: string, value: string): Promise<boolean> {
  const cs = getTelegramWebApp()?.CloudStorage;
  if (!cs?.setItem) return false;
  return new Promise((resolve) => {
    try {
      cs.setItem?.(key, value, (err, success) => {
        if (err != null) resolve(false);
        else resolve(Boolean(success));
      });
    } catch {
      resolve(false);
    }
  });
}

export async function cloudStorageRemove(key: string): Promise<void> {
  const cs = getTelegramWebApp()?.CloudStorage;
  if (!cs?.removeItem) return;
  return new Promise((resolve) => {
    try {
      cs.removeItem?.(key, () => resolve());
    } catch {
      resolve();
    }
  });
}
