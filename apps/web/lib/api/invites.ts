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

export type ManageableRole = "admin" | "operator" | "bartender";

export interface TeamMemberRow {
  id: string;
  full_name: string;
  role: "owner" | "admin" | "operator" | string;
  /** Display-only job title (optional). */
  job_title?: string | null;
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
  role: "admin" | "operator" | "bartender";
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
  jobTitle?: { set: true; value: string | null },
): Promise<ApiResult<{ ok: string; role: string; job_title: string | null }>> {
  const body: { role: ManageableRole; job_title?: string | null } = { role };
  if (jobTitle?.set === true) {
    body.job_title = jobTitle.value;
  }
  return api.post<{ ok: string; role: string; job_title: string | null }>(
    `/v1/team/members/${userId}/role`,
    body,
  );
}

export async function removeMember(
  userId: string,
): Promise<ApiResult<{ ok: string }>> {
  return api.post<{ ok: string }>(`/v1/team/members/${userId}/deactivate`, {});
}
