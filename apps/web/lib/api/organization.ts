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
