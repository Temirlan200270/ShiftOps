"use client";

/**
 * Owner / admin analytics overview client.
 *
 * Why one shape, not many
 * -----------------------
 * The backend returns every analytics block in a single
 * ``/v1/analytics/overview`` payload — see
 * ``apps/api/shiftops_api/api/v1/analytics.py`` for the rationale. We
 * mirror that here so the UI does one fetch and renders many cards from
 * the same store of truth. ``previous`` is a recursive payload of the
 * same shape (without its own ``previous``), filled when ``compare`` is
 * requested.
 */

import { api, type ApiResult } from "@/lib/api/client";

export type DensityFlag = "ok" | "low" | "empty";

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
  role: string;
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

export interface AnalyticsTemplate {
  templateId: string;
  templateName: string;
  shiftsTotal: number;
  shiftsWithViolations: number;
  averageScore: number | null;
}

export interface AnalyticsCriticality {
  criticality: "critical" | "required" | "optional" | string;
  tasksTotal: number;
  done: number;
  skipped: number;
  waiverRejected: number;
  suspiciousAttachments: number;
}

export interface AnalyticsAntifake {
  attachmentsTotal: number;
  suspiciousTotal: number;
  suspiciousRate: number | null;
}

export interface AnalyticsSla {
  thresholdMin: number;
  shiftsWithActual: number;
  lateCount: number;
  lateRate: number | null;
  avgLateMin: number | null;
}

export interface AnalyticsRoleSplit {
  operator: AnalyticsKpi;
  bartender: AnalyticsKpi;
}

export interface AnalyticsDensity {
  kpis: DensityFlag;
  heatmap: DensityFlag;
  violators: DensityFlag;
  templates: DensityFlag;
}

export interface AnalyticsOverview {
  rangeFrom: string;
  rangeTo: string;
  days: number;
  kpis: AnalyticsKpi;
  heatmap: AnalyticsHeatmapCell[];
  topViolators: AnalyticsViolator[];
  locations: AnalyticsLocation[];
  templates: AnalyticsTemplate[];
  criticality: AnalyticsCriticality[];
  antifake: AnalyticsAntifake | null;
  slaLateStart: AnalyticsSla | null;
  roleSplit: AnalyticsRoleSplit | null;
  density: AnalyticsDensity | null;
  previous: AnalyticsOverview | null;
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
  /** Present on API v2; older servers omit it. */
  role?: string;
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

interface TemplateDTO {
  template_id: string;
  template_name: string;
  shifts_total: number;
  shifts_with_violations: number;
  average_score: number | null;
}

interface CriticalityDTO {
  criticality: string;
  tasks_total: number;
  done: number;
  skipped: number;
  waiver_rejected: number;
  suspicious_attachments: number;
}

interface AntifakeDTO {
  attachments_total: number;
  suspicious_total: number;
  suspicious_rate: number | null;
}

interface SlaDTO {
  threshold_min: number;
  shifts_with_actual: number;
  late_count: number;
  late_rate: number | null;
  avg_late_min: number | null;
}

interface RoleSplitDTO {
  operator: KpiDTO;
  bartender: KpiDTO;
}

interface DensityDTO {
  kpis: DensityFlag;
  heatmap: DensityFlag;
  violators: DensityFlag;
  templates: DensityFlag;
}

interface OverviewDTO {
  range_from: string;
  range_to: string;
  days: number;
  kpis: KpiDTO;
  heatmap?: HeatmapDTO[];
  top_violators?: ViolatorDTO[];
  locations?: LocationDTO[];
  /** v2 fields — absent on older `/overview` responses. */
  templates?: TemplateDTO[];
  criticality?: CriticalityDTO[];
  antifake: AntifakeDTO | null;
  sla_late_start: SlaDTO | null;
  role_split: RoleSplitDTO | null;
  density: DensityDTO | null;
  previous: OverviewDTO | null;
}

function kpiFromDto(dto: KpiDTO): AnalyticsKpi {
  return {
    shiftsClosed: dto.shifts_closed,
    shiftsClean: dto.shifts_clean,
    shiftsWithViolations: dto.shifts_with_violations,
    averageScore: dto.average_score,
    cleanlinessRate: dto.cleanliness_rate,
  };
}

function overviewFromDto(dto: OverviewDTO): AnalyticsOverview {
  // Older API deployments (or partial JSON) may omit v2 list fields — treat
  // as empty arrays so the UI never throws on `.map()` during sheet open/close
  // or after a hot reload against a stale edge.
  const heatmap = dto.heatmap ?? [];
  const topViolators = dto.top_violators ?? [];
  const locations = dto.locations ?? [];
  const templates = dto.templates ?? [];
  const criticality = dto.criticality ?? [];

  return {
    rangeFrom: dto.range_from,
    rangeTo: dto.range_to,
    days: dto.days,
    kpis: kpiFromDto(dto.kpis),
    heatmap: heatmap.map((c) => ({
      dayOfWeek: c.day_of_week,
      hourOfDay: c.hour_of_day,
      shiftCount: c.shift_count,
      averageScore: c.average_score,
    })),
    topViolators: topViolators.map((v) => ({
      userId: v.user_id,
      fullName: v.full_name,
      role: v.role ?? "",
      shiftsTotal: v.shifts_total,
      shiftsWithViolations: v.shifts_with_violations,
      averageScore: v.average_score,
    })),
    locations: locations.map((loc) => ({
      locationId: loc.location_id,
      locationName: loc.location_name,
      shiftsTotal: loc.shifts_total,
      shiftsWithViolations: loc.shifts_with_violations,
      averageScore: loc.average_score,
    })),
    templates: templates.map((t) => ({
      templateId: t.template_id,
      templateName: t.template_name,
      shiftsTotal: t.shifts_total,
      shiftsWithViolations: t.shifts_with_violations,
      averageScore: t.average_score,
    })),
    criticality: criticality.map((c) => ({
      criticality: c.criticality,
      tasksTotal: c.tasks_total,
      done: c.done,
      skipped: c.skipped,
      waiverRejected: c.waiver_rejected,
      suspiciousAttachments: c.suspicious_attachments,
    })),
    antifake: dto.antifake
      ? {
          attachmentsTotal: dto.antifake.attachments_total,
          suspiciousTotal: dto.antifake.suspicious_total,
          suspiciousRate: dto.antifake.suspicious_rate,
        }
      : null,
    slaLateStart: dto.sla_late_start
      ? {
          thresholdMin: dto.sla_late_start.threshold_min,
          shiftsWithActual: dto.sla_late_start.shifts_with_actual,
          lateCount: dto.sla_late_start.late_count,
          lateRate: dto.sla_late_start.late_rate,
          avgLateMin: dto.sla_late_start.avg_late_min,
        }
      : null,
    roleSplit: dto.role_split
      ? {
          operator: kpiFromDto(dto.role_split.operator),
          bartender: kpiFromDto(dto.role_split.bartender),
        }
      : null,
    density: dto.density
      ? {
          kpis: dto.density.kpis,
          heatmap: dto.density.heatmap,
          violators: dto.density.violators,
          templates: dto.density.templates,
        }
      : null,
    previous: dto.previous ? overviewFromDto(dto.previous) : null,
  };
}

export interface FetchOverviewParams {
  days?: number;
  /** ISO date (YYYY-MM-DD). When provided alongside `to`, overrides `days`. */
  from?: string;
  /** ISO date (YYYY-MM-DD). */
  to?: string;
  compare?: boolean;
  violatorsLimit?: number;
  locationId?: string | null;
}

export async function fetchOverview(
  params: FetchOverviewParams = {},
): Promise<ApiResult<AnalyticsOverview>> {
  const qs = new URLSearchParams();
  if (params.from && params.to) {
    qs.set("from", params.from);
    qs.set("to", params.to);
  } else if (params.days) {
    qs.set("days", String(params.days));
  }
  if (params.compare) qs.set("compare", "true");
  if (params.violatorsLimit) qs.set("violators_limit", String(params.violatorsLimit));
  if (params.locationId) qs.set("location_id", params.locationId);
  const path = `/v1/analytics/overview${qs.toString() ? `?${qs.toString()}` : ""}`;
  const result = await api.get<OverviewDTO>(path);
  if (!result.ok) return result;
  try {
    return { ok: true, status: result.status, data: overviewFromDto(result.data) };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return {
      ok: false,
      status: 500,
      code: "overview_parse_failed",
      message,
    };
  }
}
