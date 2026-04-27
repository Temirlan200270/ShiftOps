"use client";

/**
 * Owner / admin analytics overview client.
 *
 * Why one shape, not four
 * -----------------------
 * The backend returns KPIs, heatmap, top-violators and locations in a
 * single ``/v1/analytics/overview`` payload — see
 * ``apps/api/shiftops_api/api/v1/analytics.py`` for the rationale. We
 * mirror that here so the UI does one fetch and renders four cards from
 * the same store of truth.
 */

import { api, type ApiResult } from "@/lib/api/client";

export interface AnalyticsKpi {
  shiftsClosed: number;
  shiftsClean: number;
  shiftsWithViolations: number;
  averageScore: number | null;
  cleanlinessRate: number | null;
}

export interface AnalyticsHeatmapCell {
  dayOfWeek: number;
  hourOfDay: number;
  shiftCount: number;
  averageScore: number | null;
}

export interface AnalyticsViolator {
  userId: string;
  fullName: string;
  shiftsTotal: number;
  shiftsWithViolations: number;
  averageScore: number | null;
}

export interface AnalyticsLocation {
  locationId: string;
  locationName: string;
  shiftsTotal: number;
  shiftsWithViolations: number;
  averageScore: number | null;
}

export interface AnalyticsOverview {
  rangeFrom: string;
  rangeTo: string;
  days: number;
  kpis: AnalyticsKpi;
  heatmap: AnalyticsHeatmapCell[];
  topViolators: AnalyticsViolator[];
  locations: AnalyticsLocation[];
}

interface KpiDTO {
  shifts_closed: number;
  shifts_clean: number;
  shifts_with_violations: number;
  average_score: number | null;
  cleanliness_rate: number | null;
}

interface HeatmapDTO {
  day_of_week: number;
  hour_of_day: number;
  shift_count: number;
  average_score: number | null;
}

interface ViolatorDTO {
  user_id: string;
  full_name: string;
  shifts_total: number;
  shifts_with_violations: number;
  average_score: number | null;
}

interface LocationDTO {
  location_id: string;
  location_name: string;
  shifts_total: number;
  shifts_with_violations: number;
  average_score: number | null;
}

interface OverviewDTO {
  range_from: string;
  range_to: string;
  days: number;
  kpis: KpiDTO;
  heatmap: HeatmapDTO[];
  top_violators: ViolatorDTO[];
  locations: LocationDTO[];
}

export async function fetchOverview(
  params: { days?: number; locationId?: string | null } = {},
): Promise<ApiResult<AnalyticsOverview>> {
  const qs = new URLSearchParams();
  if (params.days) qs.set("days", String(params.days));
  if (params.locationId) qs.set("location_id", params.locationId);
  const path = `/v1/analytics/overview${qs.toString() ? `?${qs.toString()}` : ""}`;
  const result = await api.get<OverviewDTO>(path);
  if (!result.ok) return result;
  const dto = result.data;
  return {
    ok: true,
    status: result.status,
    data: {
      rangeFrom: dto.range_from,
      rangeTo: dto.range_to,
      days: dto.days,
      kpis: {
        shiftsClosed: dto.kpis.shifts_closed,
        shiftsClean: dto.kpis.shifts_clean,
        shiftsWithViolations: dto.kpis.shifts_with_violations,
        averageScore: dto.kpis.average_score,
        cleanlinessRate: dto.kpis.cleanliness_rate,
      },
      heatmap: dto.heatmap.map((c) => ({
        dayOfWeek: c.day_of_week,
        hourOfDay: c.hour_of_day,
        shiftCount: c.shift_count,
        averageScore: c.average_score,
      })),
      topViolators: dto.top_violators.map((v) => ({
        userId: v.user_id,
        fullName: v.full_name,
        shiftsTotal: v.shifts_total,
        shiftsWithViolations: v.shifts_with_violations,
        averageScore: v.average_score,
      })),
      locations: dto.locations.map((loc) => ({
        locationId: loc.location_id,
        locationName: loc.location_name,
        shiftsTotal: loc.shifts_total,
        shiftsWithViolations: loc.shifts_with_violations,
        averageScore: loc.average_score,
      })),
    },
  };
}
