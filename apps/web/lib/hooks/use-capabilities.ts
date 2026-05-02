"use client";

import * as React from "react";

import { getCapabilities, type AppCapabilities } from "@/lib/auth/capabilities";
import { useAuthStore } from "@/lib/stores/auth-store";
import type { UserRole } from "@/lib/types";

const DEFAULT_ROLE: UserRole = "operator";

/**
 * Memoized capabilities for the current session (role + optional god mode).
 */
export function useCapabilities(): AppCapabilities {
  const me = useAuthStore((s) => s.me);
  const superAdminTgId = process.env.NEXT_PUBLIC_SUPER_ADMIN_TG_ID;

  return React.useMemo(
    () =>
      getCapabilities({
        role: me?.role ?? DEFAULT_ROLE,
        tgUserId: me?.tgUserId ?? null,
        superAdminTgId,
      }),
    [me?.role, me?.tgUserId, superAdminTgId],
  );
}
