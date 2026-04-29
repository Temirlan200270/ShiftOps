"use client";

import { api, type ApiResult } from "@/lib/api/client";

export interface LocationRow {
  id: string;
  name: string;
  timezone: string;
}

export interface CreateInviteResult {
  invite_id: string;
  token: string;
  deep_link: string;
  expires_at: string;
}

export interface TeamSummary {
  other_members_count: number;
  org_total_members: number;
}

export type ManageableRole = "admin" | "operator";

export interface TeamMemberRow {
  id: string;
  full_name: string;
  role: "owner" | "admin" | "operator" | string;
  is_active: boolean;
  tg_user_id: number | null;
  tg_username: string | null;
  can_deactivate: boolean;
  cannot_deactivate_reason: string | null;
  can_change_role: boolean;
  cannot_change_role_reason: string | null;
}

export async function fetchLocations(): Promise<ApiResult<LocationRow[]>> {
  return api.get<LocationRow[]>("/v1/locations");
}

export async function fetchTeamSummary(): Promise<ApiResult<TeamSummary>> {
  return api.get<TeamSummary>("/v1/team/summary");
}

export async function fetchTeamMembers(includeInactive?: boolean): Promise<ApiResult<TeamMemberRow[]>> {
  const q = includeInactive === true ? "?include_inactive=true" : "";
  return api.get<TeamMemberRow[]>(`/v1/team/members${q}`);
}

export async function createInvite(payload: {
  role: "admin" | "operator";
  location_id: string | null;
  expires_in_hours: number;
}): Promise<ApiResult<CreateInviteResult>> {
  return api.post<CreateInviteResult>("/v1/invites", {
    role: payload.role,
    location_id: payload.location_id,
    expires_in_hours: payload.expires_in_hours,
  });
}

export async function changeMemberRole(
  userId: string,
  role: ManageableRole,
): Promise<ApiResult<{ ok: string; role: string }>> {
  return api.post<{ ok: string; role: string }>(`/v1/team/members/${userId}/role`, { role });
}

export async function removeMember(
  userId: string,
): Promise<ApiResult<{ ok: string }>> {
  return api.post<{ ok: string }>(`/v1/team/members/${userId}/deactivate`, {});
}
