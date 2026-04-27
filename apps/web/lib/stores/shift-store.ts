"use client";

import { create } from "zustand";

import type { ShiftSummary, TaskCard } from "@/lib/types";

/**
 * Holds the currently loaded shift in memory.
 *
 * We keep a single shift in memory at a time — operators have at most one
 * active shift. The store exposes:
 *
 * - `setShift(s)` — refresh after fetch.
 * - `markTaskOptimistic(id, status)` — flip status locally for instant
 *   feedback while the network call is in flight; on failure we re-fetch.
 *
 * No persistence: shifts are server-of-truth and we don't want stale tasks
 * showing after a relog.
 */

interface ShiftState {
  shift: ShiftSummary | null;
  setShift: (shift: ShiftSummary | null) => void;
  markTaskOptimistic: (taskId: string, patch: Partial<TaskCard>) => void;
}

export const useShiftStore = create<ShiftState>((set) => ({
  shift: null,
  setShift: (shift) => set({ shift }),
  markTaskOptimistic: (taskId, patch) =>
    set((state) => {
      if (!state.shift) return state;
      return {
        shift: {
          ...state.shift,
          tasks: state.shift.tasks.map((t) => (t.id === taskId ? { ...t, ...patch } : t)),
        },
      };
    }),
}));
