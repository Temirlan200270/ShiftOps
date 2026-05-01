"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * Client-only preferences (localStorage via zustand persist).
 * Biometric gate defaults **off** — opt-in demo / comfort feature.
 */
interface PreferencesState {
  shiftCloseBiometricEnabled: boolean;
  setShiftCloseBiometricEnabled: (value: boolean) => void;
}

export const usePreferencesStore = create<PreferencesState>()(
  persist(
    (set) => ({
      shiftCloseBiometricEnabled: false,
      setShiftCloseBiometricEnabled: (value) => set({ shiftCloseBiometricEnabled: value }),
    }),
    { name: "shiftops-preferences-v1" },
  ),
);
