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

export async function fetchLocations(): Promise<ApiResult<LocationRow[]>> {
  return api.get<LocationRow[]>("/v1/locations");
}

export async function fetchTeamSummary(): Promise<ApiResult<TeamSummary>> {
  return api.get<TeamSummary>("/v1/team/summary");
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
