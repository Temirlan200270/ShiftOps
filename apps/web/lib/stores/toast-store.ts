"use client";

import { create } from "zustand";

/**
 * Why a custom store and not react-hot-toast / sonner?
 *
 * - Zero extra deps: we already use Zustand for shift state.
 * - Telegram WebApp blocks fixed positioning under the bottom safe area
 *   inconsistently across iOS / Android; controlling rendering ourselves
 *   lets us anchor the viewport above MainButton when it's visible.
 * - Keeps the bundle small (every kb counts on bartender's 4G).
 */

export type ToastVariant = "default" | "success" | "warning" | "critical";

export interface ToastEntry {
  id: string;
  title?: string;
  description?: string;
  variant?: ToastVariant;
  duration?: number;
}

interface ToastState {
  toasts: ToastEntry[];
  push: (toast: Omit<ToastEntry, "id"> & { id?: string }) => string;
  dismiss: (id: string) => void;
}

export const useToastStore = create<ToastState>((set) => ({
  toasts: [],
  push: (toast) => {
    const id = toast.id ?? crypto.randomUUID();
    set((state) => ({ toasts: [...state.toasts, { ...toast, id }] }));
    return id;
  },
  dismiss: (id) => set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) })),
}));

export function toast(input: Omit<ToastEntry, "id">): string {
  return useToastStore.getState().push(input);
}
