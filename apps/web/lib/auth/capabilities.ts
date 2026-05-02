/**
 * Client-side capability flags for Adaptive UI.
 *
 * Security: API + RLS remain authoritative. These flags only drive navigation
 * and layout; a tampered client still gets 403 from the server.
 *
 * God mode: when `me.tgUserId` matches `NEXT_PUBLIC_SUPER_ADMIN_TG_ID` (same
 * numeric Telegram user id as API `SUPER_ADMIN_TG_ID`), treat as full access
 * regardless of org role (e.g. testing as operator in a pilot org).
 *
 * Team API alignment:
 * - GET /team: `_view_team` = admin | owner  → `canViewTeam`
 * - Mutations: `_require_manager` = owner | platform super-admin → `canManageTeamMembers`
 *   (client god mode mirrors platform super-admin for UI; server still enforces.)
 */

import type { UserRole } from "@/lib/types";

export interface AppCapabilities {
  isGodMode: boolean;
  /** True when org role is operator or bartender (ignores god — use can* flags for UI). */
  isLineStaff: boolean;
  /** owner or admin in the org (not derived from god mode). */
  isOrgAdmin: boolean;
  /** Full admin menu: analytics, templates, live, team screen entry, etc. */
  canAccessAdminModules: boolean;
  canViewAnalytics: boolean;
  canManageTemplates: boolean;
  canViewLiveMonitor: boolean;
  canViewBusinessHours: boolean;
  canImportCsv: boolean;
  canViewAudit: boolean;
  /** Open team screen (list); same as API view permission. */
  canViewTeam: boolean;
  /** Change roles / deactivate / invite management affordances; owner + god only. */
  canManageTeamMembers: boolean;
  canOpenHistory: boolean;
  canOpenSettings: boolean;
  canOpenSwapRequests: boolean;
}

export interface GetCapabilitiesInput {
  role: UserRole;
  tgUserId: number | null;
  /** Pass `process.env.NEXT_PUBLIC_SUPER_ADMIN_TG_ID` from the client bundle. */
  superAdminTgId: string | null | undefined;
}

/** Normalize env: trim; compare as string to `String(tgUserId)` for stable matching. */
export function getCapabilities(input: GetCapabilitiesInput): AppCapabilities {
  const raw = (input.superAdminTgId ?? "").trim();
  const isGodMode =
    raw !== "" && input.tgUserId !== null && String(input.tgUserId) === raw;

  const isOwner = input.role === "owner";
  const isAdmin = input.role === "admin";
  const isLine = input.role === "operator" || input.role === "bartender";

  const canAccessAdminModules = isGodMode || isOwner || isAdmin;

  const canManageTeamMembers = isGodMode || isOwner;

  return {
    isGodMode,
    isLineStaff: isLine,
    isOrgAdmin: isOwner || isAdmin,
    canAccessAdminModules,
    canViewAnalytics: canAccessAdminModules,
    canManageTemplates: canAccessAdminModules,
    canViewLiveMonitor: canAccessAdminModules,
    canViewBusinessHours: canAccessAdminModules,
    canImportCsv: canAccessAdminModules,
    canViewAudit: canAccessAdminModules,
    canViewTeam: canAccessAdminModules,
    canManageTeamMembers,
    canOpenHistory: true,
    canOpenSettings: true,
    canOpenSwapRequests: true,
  };
}
