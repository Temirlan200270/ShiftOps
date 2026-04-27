"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * Auth state.
 *
 * - `accessToken` is short-lived (15 min) and refreshed via the back-end.
 * - `refreshToken` is in IndexedDB-backed persistent storage so reopening the
 *   TWA in Telegram doesn't force a re-handshake every time.
 * - `me` is hydrated by the auth handshake response. We store the role here
 *   to drive UI guards client-side; the API still re-checks server-side.
 *
 * Why Zustand `persist` and not `next-auth`: we have a Telegram-only auth
 * flow, no OAuth providers, no email/password — `next-auth` would add
 * overhead without value.
 */

import type { UserRole } from "@/lib/types";

export interface MeProfile {
  id: string;
  fullName: string;
  role: UserRole;
  organizationId: string;
  // Backend sends NULL when the user row has no locale set (rare — only
  // happens for users imported from CSV without a Telegram language_code
  // ever flowing in). The TWA falls back to the Telegram WebApp's own
  // language detection in that case.
  locale: "ru" | "en" | null;
  tgUserId: number | null;
}

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  me: MeProfile | null;
  /** Set when `performHandshake` fails; not persisted — otherwise the splash would spin forever. */
  handshakeError: string | null;
  setSession: (input: {
    accessToken: string;
    refreshToken: string;
    me: MeProfile;
  }) => void;
  setHandshakeError: (message: string | null) => void;
  clear: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      refreshToken: null,
      me: null,
      handshakeError: null,
      setSession: ({ accessToken, refreshToken, me }) =>
        set({ accessToken, refreshToken, me, handshakeError: null }),
      setHandshakeError: (message) => set({ handshakeError: message }),
      clear: () =>
        set({ accessToken: null, refreshToken: null, me: null, handshakeError: null }),
    }),
    {
      name: "shiftops.auth.v1",
      partialize: (state) => ({
        refreshToken: state.refreshToken,
        me: state.me,
      }),
    },
  ),
);
