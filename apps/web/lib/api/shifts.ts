"use client";

import { api, type ApiResult } from "@/lib/api/client";
import type { ScoreBreakdown, ShiftSummary, TaskCard } from "@/lib/types";

interface ShiftHeadDTO {
  id: string;
  template_name: string;
  status: ShiftSummary["status"];
  score: number | null;
  progress_done: number;
  progress_total: number;
  scheduled_start: string;
  scheduled_end: string;
  actual_start: string | null;
  actual_end: string | null;
  operator_full_name: string;
  slot_index: number;
  station_label: string | null;
}

interface TaskCardDTO {
  id: string;
  title: string;
  description: string | null;
  section: string | null;
  criticality: TaskCard["criticality"];
  requires_photo: boolean;
  requires_comment: boolean;
  status: TaskCard["status"];
  comment: string | null;
  has_attachment: boolean;
}

interface CurrentShiftDTO {
  shift: ShiftHeadDTO;
  tasks: TaskCardDTO[];
}

interface ScoreBreakdownDTO {
  completion: number;
  critical_compliance: number;
  timeliness: number;
  photo_quality: number;
}

interface CloseShiftDTO {
  shift_id: string;
  final_status: string;
  score: number;
  breakdown: ScoreBreakdownDTO;
  formula_version: number;
  missed_required: number;
  missed_critical: number;
}

function breakdownFromDto(dto: ScoreBreakdownDTO): ScoreBreakdown {
  return {
    completion: dto.completion,
    criticalCompliance: dto.critical_compliance,
    timeliness: dto.timeliness,
    photoQuality: dto.photo_quality,
  };
}

function fromCurrentShift(dto: CurrentShiftDTO): ShiftSummary {
  return {
    id: dto.shift.id,
    templateName: dto.shift.template_name,
    status: dto.shift.status,
    scheduledStart: dto.shift.scheduled_start,
    scheduledEnd: dto.shift.scheduled_end,
    actualStart: dto.shift.actual_start,
    actualEnd: dto.shift.actual_end,
    score: dto.shift.score,
    // GET /v1/shifts/me does not include the breakdown — only the close
    // response and history do. We surface null and the UI hides the panel.
    scoreBreakdown: null,
    formulaVersion: null,
    operatorFullName: dto.shift.operator_full_name,
    slotIndex: dto.shift.slot_index,
    stationLabel: dto.shift.station_label,
    tasks: dto.tasks.map((t) => ({
      id: t.id,
      title: t.title,
      description: t.description,
      section: t.section ?? null,
      criticality: t.criticality,
      status: t.status,
      requiresPhoto: t.requires_photo,
      requiresComment: t.requires_comment,
      comment: t.comment,
      hasAttachment: t.has_attachment,
    })),
  };
}

export async function fetchMyShift(): Promise<ApiResult<ShiftSummary | null>> {
  const result = await api.get<CurrentShiftDTO>("/v1/shifts/me");
  if (!result.ok) {
    if (result.status === 404) return { ok: true, status: 404, data: null };
    return result;
  }
  return { ok: true, status: result.status, data: fromCurrentShift(result.data) };
}

export interface VacantShift {
  id: string;
  templateName: string;
  templateId: string;
  roleTarget: string;
  locationId: string;
  locationName: string;
  scheduledStart: string;
  scheduledEnd: string;
  stationLabel: string | null;
  slotIndex: number;
}

interface VacantShiftDTO {
  id: string;
  template_name: string;
  template_id: string;
  role_target: string;
  location_id: string;
  location_name: string;
  scheduled_start: string;
  scheduled_end: string;
  station_label: string | null;
  slot_index: number;
}

export async function fetchAvailableShifts(input?: {
  locationId?: string | null;
}): Promise<ApiResult<VacantShift[]>> {
  const params = new URLSearchParams();
  if (input?.locationId) params.set("location_id", input.locationId);
  const qs = params.toString();
  const path = `/v1/shifts/available${qs ? `?${qs}` : ""}`;
  const result = await api.get<VacantShiftDTO[]>(path);
  if (!result.ok) return result;
  return {
    ok: true,
    status: result.status,
    data: result.data.map((row) => ({
      id: row.id,
      templateName: row.template_name,
      templateId: row.template_id,
      roleTarget: row.role_target,
      locationId: row.location_id,
      locationName: row.location_name,
      scheduledStart: row.scheduled_start,
      scheduledEnd: row.scheduled_end,
      stationLabel: row.station_label,
      slotIndex: row.slot_index,
    })),
  };
}

export async function claimShift(
  shiftId: string,
  geo?: StartShiftGeo,
): Promise<ApiResult<ShiftSummary | null>> {
  const result = await api.post<CurrentShiftDTO>(`/v1/shifts/${shiftId}/claim`, geo ?? {});
  if (!result.ok) return result;
  return { ok: true, status: result.status, data: fromCurrentShift(result.data) };
}

export interface StartShiftGeo {
  client_latitude: number;
  client_longitude: number;
  client_accuracy_m?: number;
}

export async function readClientGeoForShiftStart(): Promise<StartShiftGeo | undefined> {
  if (typeof navigator === "undefined" || !navigator.geolocation) {
    return undefined;
  }
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        resolve({
          client_latitude: pos.coords.latitude,
          client_longitude: pos.coords.longitude,
          client_accuracy_m:
            pos.coords.accuracy !== undefined ? pos.coords.accuracy : undefined,
        });
      },
      () => resolve(undefined),
      { enableHighAccuracy: true, timeout: 8000, maximumAge: 60_000 },
    );
  });
}

export async function startShift(
  shiftId: string,
  geo?: StartShiftGeo,
): Promise<ApiResult<ShiftSummary | null>> {
  const result = await api.post<CurrentShiftDTO>(`/v1/shifts/${shiftId}/start`, geo);
  if (!result.ok) return result;
  return { ok: true, status: result.status, data: fromCurrentShift(result.data) };
}

export async function completeTask(input: {
  taskId: string;
  comment?: string;
  photo?: Blob;
}): Promise<ApiResult<{ status: string; suspicious: boolean }>> {
  const form = new FormData();
  if (input.comment) form.set("comment", input.comment);
  if (input.photo) form.set("photo", input.photo, "photo.jpg");
  const result = await api.postForm<{
    task_id: string;
    status: string;
    suspicious: boolean;
  }>(`/v1/shifts/tasks/${input.taskId}/complete`, form);
  if (!result.ok) return result;
  return {
    ok: true,
    status: result.status,
    data: { status: result.data.status, suspicious: result.data.suspicious },
  };
}

export async function requestWaiver(input: {
  taskId: string;
  reason: string;
}): Promise<ApiResult<{ status: string }>> {
  return api.post(`/v1/shifts/tasks/${input.taskId}/waiver`, {
    reason: input.reason,
  });
}

export interface ClosedShiftPatch {
  shiftId: string;
  finalStatus: ShiftSummary["status"];
  score: number;
  breakdown: ScoreBreakdown;
  formulaVersion: number;
  missedRequired: number;
  missedCritical: number;
}

/**
 * Closes the shift and returns the close-time delta. Caller is responsible
 * for merging it onto the in-memory shift (the task list, scheduled times,
 * etc. are unchanged — only `status`, `score`, `scoreBreakdown` move).
 *
 * Why we don't re-fetch from `/v1/shifts/me`: that endpoint returns 404 for
 * closed shifts (it only serves the *current* shift). The score breakdown
 * lives on the close response. The history / detail endpoint that returns
 * a closed shift's full data lands in B2.
 */
export interface HistoryItem {
  id: string;
  templateName: string;
  status: ShiftSummary["status"];
  score: number | null;
  formulaVersion: number;
  breakdown: ScoreBreakdown | null;
  scheduledStart: string;
  scheduledEnd: string;
  actualStart: string | null;
  actualEnd: string | null;
  tasksTotal: number;
  tasksDone: number;
  handoverSummary: string | null;
  slotIndex: number;
  stationLabel: string | null;
  delayReason: string | null;
}

export interface HistoryPage {
  items: HistoryItem[];
  nextCursor: string | null;
}

interface HistoryRowDTO {
  id: string;
  template_name: string;
  status: ShiftSummary["status"];
  score: number | null;
  formula_version: number;
  breakdown: ScoreBreakdownDTO | null;
  scheduled_start: string;
  scheduled_end: string;
  actual_start: string | null;
  actual_end: string | null;
  tasks_total: number;
  tasks_done: number;
  handover_summary?: string | null;
  slot_index: number;
  station_label: string | null;
  delay_reason: string | null;
}

interface HistoryResponseDTO {
  items: HistoryRowDTO[];
  next_cursor: string | null;
}

export async function fetchHistory(input: {
  cursor?: string | null;
  limit?: number;
  /** Admin/owner only: scope history to a specific operator. */
  userId?: string | null;
  locationId?: string | null;
  /** ISO date (YYYY-MM-DD). */
  from?: string | null;
  /** ISO date (YYYY-MM-DD). */
  to?: string | null;
  slotIndex?: number | null;
  stationLabel?: string | null;
  /** When true, only shifts with NULL station_label (must match analytics post rows without a label). */
  stationLabelEmpty?: boolean;
} = {}): Promise<ApiResult<HistoryPage>> {
  const params = new URLSearchParams();
  if (input.cursor) params.set("cursor", input.cursor);
  if (input.limit) params.set("limit", String(input.limit));
  if (input.userId) params.set("user_id", input.userId);
  if (input.locationId) params.set("location_id", input.locationId);
  if (input.from) params.set("from", input.from);
  if (input.to) params.set("to", input.to);
  if (input.slotIndex !== undefined && input.slotIndex !== null) {
    params.set("slot_index", String(input.slotIndex));
  }
  if (input.stationLabelEmpty) {
    params.set("station_label_empty", "true");
  } else if (input.stationLabel) {
    params.set("station_label", input.stationLabel);
  }
  const qs = params.toString();
  const path = `/v1/shifts/history${qs ? `?${qs}` : ""}`;
  const result = await api.get<HistoryResponseDTO>(path);
  if (!result.ok) return result;
  return {
    ok: true,
    status: result.status,
    data: {
      items: result.data.items.map((row) => ({
        id: row.id,
        templateName: row.template_name,
        status: row.status,
        score: row.score,
        formulaVersion: row.formula_version,
        breakdown: row.breakdown ? breakdownFromDto(row.breakdown) : null,
        scheduledStart: row.scheduled_start,
        scheduledEnd: row.scheduled_end,
        actualStart: row.actual_start,
        actualEnd: row.actual_end,
        tasksTotal: row.tasks_total,
        tasksDone: row.tasks_done,
        handoverSummary: row.handover_summary ?? null,
        slotIndex: row.slot_index,
        stationLabel: row.station_label,
        delayReason: row.delay_reason,
      })),
      nextCursor: result.data.next_cursor,
    },
  };
}

export async function closeShift(input: {
  shiftId: string;
  confirmViolations: boolean;
  delayReason?: string | null;
}): Promise<ApiResult<ClosedShiftPatch>> {
  const result = await api.post<CloseShiftDTO>(`/v1/shifts/${input.shiftId}/close`, {
    confirm_violations: input.confirmViolations,
    delay_reason: input.delayReason ?? null,
  });
  if (!result.ok) return result;
  const closed = result.data;
  return {
    ok: true,
    status: 200,
    data: {
      shiftId: closed.shift_id,
      finalStatus: closed.final_status as ShiftSummary["status"],
      score: closed.score,
      breakdown: breakdownFromDto(closed.breakdown),
      formulaVersion: closed.formula_version,
      missedRequired: closed.missed_required,
      missedCritical: closed.missed_critical,
    },
  };
}

export interface MyScheduledShift {
  id: string;
  templateName: string;
  locationName: string;
  scheduledStart: string;
  scheduledEnd: string;
  stationLabel: string | null;
  slotIndex: number;
}

interface MyScheduledShiftDTO {
  id: string;
  template_name: string;
  location_name: string;
  scheduled_start: string;
  scheduled_end: string;
  station_label: string | null;
  slot_index: number;
}

export async function fetchMyScheduledShifts(): Promise<ApiResult<MyScheduledShift[]>> {
  const result = await api.get<MyScheduledShiftDTO[]>("/v1/shifts/my-scheduled");
  if (!result.ok) return result;
  return {
    ok: true,
    status: result.status,
    data: result.data.map((row) => ({
      id: row.id,
      templateName: row.template_name,
      locationName: row.location_name,
      scheduledStart: row.scheduled_start,
      scheduledEnd: row.scheduled_end,
      stationLabel: row.station_label,
      slotIndex: row.slot_index,
    })),
  };
}

export interface SwapLinkPreview {
  shiftId: string;
  templateName: string;
  locationName: string;
  scheduledStart: string;
  scheduledEnd: string;
  stationLabel: string | null;
  slotIndex: number;
  proposerUserId: string;
  proposerFullName: string;
}

interface SwapLinkPreviewDTO {
  shift_id: string;
  template_name: string;
  location_name: string;
  scheduled_start: string;
  scheduled_end: string;
  station_label: string | null;
  slot_index: number;
  proposer_user_id: string;
  proposer_full_name: string;
}

export async function fetchSwapLinkPreview(
  proposerShiftId: string,
): Promise<ApiResult<SwapLinkPreview>> {
  const result = await api.get<SwapLinkPreviewDTO>(
    `/v1/shifts/${proposerShiftId}/swap-link-preview`,
  );
  if (!result.ok) return result;
  const p = result.data;
  return {
    ok: true,
    status: result.status,
    data: {
      shiftId: p.shift_id,
      templateName: p.template_name,
      locationName: p.location_name,
      scheduledStart: p.scheduled_start,
      scheduledEnd: p.scheduled_end,
      stationLabel: p.station_label,
      slotIndex: p.slot_index,
      proposerUserId: p.proposer_user_id,
      proposerFullName: p.proposer_full_name,
    },
  };
}

export interface SwapRequestRow {
  id: string;
  status: string;
  message: string | null;
  createdAt: string;
  resolvedAt: string | null;
  proposerUserId: string;
  proposerName: string;
  counterpartyUserId: string;
  counterpartyName: string;
  proposerShiftId: string;
  counterpartyShiftId: string;
}

interface SwapRequestRowDTO {
  id: string;
  status: string;
  message: string | null;
  created_at: string;
  resolved_at: string | null;
  proposer_user_id: string;
  proposer_name: string;
  counterparty_user_id: string;
  counterparty_name: string;
  proposer_shift_id: string;
  counterparty_shift_id: string;
}

function mapSwapRow(row: SwapRequestRowDTO): SwapRequestRow {
  return {
    id: row.id,
    status: row.status,
    message: row.message,
    createdAt: row.created_at,
    resolvedAt: row.resolved_at,
    proposerUserId: row.proposer_user_id,
    proposerName: row.proposer_name,
    counterpartyUserId: row.counterparty_user_id,
    counterpartyName: row.counterparty_name,
    proposerShiftId: row.proposer_shift_id,
    counterpartyShiftId: row.counterparty_shift_id,
  };
}

export async function fetchSwapRequests(
  direction: "in" | "out",
): Promise<ApiResult<SwapRequestRow[]>> {
  const result = await api.get<SwapRequestRowDTO[]>(
    `/v1/shifts/swap-requests?direction=${direction}`,
  );
  if (!result.ok) return result;
  return {
    ok: true,
    status: result.status,
    data: result.data.map(mapSwapRow),
  };
}

export async function createSwapRequest(input: {
  proposerShiftId: string;
  counterpartyShiftId: string;
  message?: string | null;
}): Promise<ApiResult<{ id: string }>> {
  const result = await api.post<{ id: string }>("/v1/shifts/swap-requests", {
    proposer_shift_id: input.proposerShiftId,
    counterparty_shift_id: input.counterpartyShiftId,
    message: input.message ?? null,
  });
  if (!result.ok) return result;
  return { ok: true, status: result.status, data: { id: result.data.id } };
}

export async function acceptSwapRequest(requestId: string): Promise<ApiResult<void>> {
  return api.post<void>(`/v1/shifts/swap-requests/${requestId}/accept`);
}

export async function declineSwapRequest(requestId: string): Promise<ApiResult<void>> {
  return api.post<void>(`/v1/shifts/swap-requests/${requestId}/decline`);
}

export async function cancelSwapRequest(requestId: string): Promise<ApiResult<void>> {
  return api.delete<void>(`/v1/shifts/swap-requests/${requestId}`);
}
