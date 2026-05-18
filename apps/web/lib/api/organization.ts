"use client";

import { api, type ApiResult } from "@/lib/api/client";

export interface RegularHoursRowDTO {
  weekdays: number[];
  opens: string;
  closes: string;
}

export interface DatedHoursRowDTO {
  on: string;
  opens: string;
  closes: string;
  note?: string | null;
}

export interface BusinessHoursDTO {
  timezone?: string | null;
  regular: RegularHoursRowDTO[];
  dated: DatedHoursRowDTO[];
}

export async function fetchBusinessHours(): Promise<ApiResult<BusinessHoursDTO>> {
  return api.get<BusinessHoursDTO>("/v1/organization/business-hours");
}

export async function saveBusinessHours(
  body: BusinessHoursDTO,
): Promise<ApiResult<BusinessHoursDTO>> {
  return api.put<BusinessHoursDTO>("/v1/organization/business-hours", body);
}

export interface ChecklistOverduePrefsDTO {
  enabled: boolean;
  delay_min: number;
  repeat_min: number;
  max_alerts: number;
}

export interface NotificationPrefsDTO {
  checklist_overdue: ChecklistOverduePrefsDTO;
}

export async function fetchNotificationPrefs(): Promise<ApiResult<NotificationPrefsDTO>> {
  return api.get<NotificationPrefsDTO>("/v1/organization/notification-prefs");
}

export async function saveNotificationPrefs(
  body: NotificationPrefsDTO,
): Promise<ApiResult<NotificationPrefsDTO>> {
  return api.put<NotificationPrefsDTO>("/v1/organization/notification-prefs", body);
}
