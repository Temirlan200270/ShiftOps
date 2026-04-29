"use client";

/**
 * Admin-only template API.
 *
 * Why a single thin file
 * ----------------------
 * There is no business logic here — just DTO ↔ model conversion. We keep
 * snake_case on the wire and camelCase in TS, which is the same convention
 * used by `lib/api/shifts.ts`. If the contract evolves we change one file.
 */

import { api, type ApiResult } from "@/lib/api/client";
import type { Criticality, UserRole } from "@/lib/types";

export interface TemplateListItem {
  id: string;
  name: string;
  roleTarget: UserRole;
  taskCount: number;
}

export interface TemplateTaskRow {
  id: string;
  title: string;
  description: string | null;
  section: string | null;
  criticality: Criticality;
  requiresPhoto: boolean;
  requiresComment: boolean;
  orderIndex: number;
}

export interface RecurrenceConfig {
  kind: "daily";
  autoCreate: boolean;
  timeOfDay: string; // "HH:MM" 24h
  durationMin: number;
  weekdays: number[]; // ISO 1..7
  timezone: string;
  locationId: string;
  defaultAssigneeId: string | null;
  leadTimeMin: number;
}

export interface TemplateDetail {
  id: string;
  name: string;
  roleTarget: UserRole;
  tasks: TemplateTaskRow[];
  recurrence: RecurrenceConfig | null;
}

export interface TemplateTaskInput {
  // Optional id: present when editing an existing task to preserve its
  // primary key; omitted/null for fresh rows.
  id: string | null;
  title: string;
  description: string | null;
  section: string | null;
  criticality: Criticality;
  requiresPhoto: boolean;
  requiresComment: boolean;
}

export interface TemplateInput {
  name: string;
  roleTarget: UserRole;
  tasks: TemplateTaskInput[];
  recurrence: RecurrenceConfig | null;
}

interface ListItemDTO {
  id: string;
  name: string;
  role_target: UserRole;
  task_count: number;
}

interface TaskDTO {
  id: string;
  title: string;
  description: string | null;
  section: string | null;
  criticality: Criticality;
  requires_photo: boolean;
  requires_comment: boolean;
  order_index: number;
}

interface RecurrenceDTO {
  kind: "daily";
  auto_create: boolean;
  time_of_day: string;
  duration_min: number;
  weekdays: number[];
  timezone: string;
  location_id: string;
  default_assignee_id: string | null;
  lead_time_min: number;
}

interface DetailDTO {
  id: string;
  name: string;
  role_target: UserRole;
  tasks: TaskDTO[];
  recurrence: RecurrenceDTO | null;
}

interface SaveResponseDTO {
  id: string;
}

function fromListDTO(dto: ListItemDTO): TemplateListItem {
  return {
    id: dto.id,
    name: dto.name,
    roleTarget: dto.role_target,
    taskCount: dto.task_count,
  };
}

function fromTaskDTO(dto: TaskDTO): TemplateTaskRow {
  return {
    id: dto.id,
    title: dto.title,
    description: dto.description,
    section: dto.section ?? null,
    criticality: dto.criticality,
    requiresPhoto: dto.requires_photo,
    requiresComment: dto.requires_comment,
    orderIndex: dto.order_index,
  };
}

function toDTO(input: TemplateInput): unknown {
  return {
    name: input.name,
    role_target: input.roleTarget,
    tasks: input.tasks.map((t) => ({
      id: t.id,
      title: t.title,
      description: t.description,
      section: t.section,
      criticality: t.criticality,
      requires_photo: t.requiresPhoto,
      requires_comment: t.requiresComment,
    })),
    recurrence: input.recurrence ? recurrenceToDTO(input.recurrence) : null,
  };
}

function recurrenceToDTO(r: RecurrenceConfig): RecurrenceDTO {
  return {
    kind: "daily",
    auto_create: r.autoCreate,
    time_of_day: r.timeOfDay,
    duration_min: r.durationMin,
    weekdays: r.weekdays,
    timezone: r.timezone,
    location_id: r.locationId,
    default_assignee_id: r.defaultAssigneeId,
    lead_time_min: r.leadTimeMin,
  };
}

function recurrenceFromDTO(dto: RecurrenceDTO): RecurrenceConfig {
  return {
    kind: "daily",
    autoCreate: dto.auto_create,
    timeOfDay: dto.time_of_day,
    durationMin: dto.duration_min,
    weekdays: dto.weekdays,
    timezone: dto.timezone,
    locationId: dto.location_id,
    defaultAssigneeId: dto.default_assignee_id,
    leadTimeMin: dto.lead_time_min,
  };
}

export async function listTemplates(): Promise<ApiResult<TemplateListItem[]>> {
  const result = await api.get<ListItemDTO[]>("/v1/templates");
  if (!result.ok) return result;
  return { ok: true, status: result.status, data: result.data.map(fromListDTO) };
}

export async function getTemplate(id: string): Promise<ApiResult<TemplateDetail>> {
  const result = await api.get<DetailDTO>(`/v1/templates/${id}`);
  if (!result.ok) return result;
  return {
    ok: true,
    status: result.status,
    data: {
      id: result.data.id,
      name: result.data.name,
      roleTarget: result.data.role_target,
      tasks: result.data.tasks.map(fromTaskDTO),
      recurrence: result.data.recurrence ? recurrenceFromDTO(result.data.recurrence) : null,
    },
  };
}

export async function createTemplate(input: TemplateInput): Promise<ApiResult<{ id: string }>> {
  const result = await api.post<SaveResponseDTO>("/v1/templates", toDTO(input));
  if (!result.ok) return result;
  return { ok: true, status: result.status, data: { id: result.data.id } };
}

export async function updateTemplate(
  id: string,
  input: TemplateInput,
): Promise<ApiResult<{ id: string }>> {
  const result = await api.put<SaveResponseDTO>(`/v1/templates/${id}`, toDTO(input));
  if (!result.ok) return result;
  return { ok: true, status: result.status, data: { id: result.data.id } };
}

export async function deleteTemplate(id: string): Promise<ApiResult<void>> {
  const result = await api.delete<void>(`/v1/templates/${id}`);
  if (!result.ok) return result;
  return { ok: true, status: result.status, data: undefined };
}

export interface ParsedTaskPreview {
  title: string;
  description: string | null;
  section: string | null;
  criticality: Criticality;
  requiresPhoto: boolean;
  requiresComment: boolean;
}

export interface ImportPreview {
  sections: string[];
  tasks: ParsedTaskPreview[];
  errors: Array<{ code: string; message: string }>;
}

export interface ImportApplyResult {
  templateId: string;
  sections: string[];
  taskCount: number;
}

interface ImportPreviewDTO {
  sections: string[];
  tasks: Array<{
    title: string;
    description: string | null;
    section: string | null;
    criticality: Criticality;
    requires_photo: boolean;
    requires_comment: boolean;
  }>;
  errors: Array<{ code: string; message: string }>;
}

interface ImportApplyDTO {
  template_id: string;
  sections: string[];
  task_count: number;
  parse_errors: Array<{ code: string; message: string }>;
}

export async function importTemplateDryRun(input: {
  name: string;
  roleTarget: UserRole;
  content: string;
}): Promise<ApiResult<ImportPreview>> {
  const result = await api.post<ImportPreviewDTO>(
    "/v1/templates/import?dry_run=true",
    {
      name: input.name,
      role_target: input.roleTarget,
      content: input.content,
    },
  );
  if (!result.ok) return result;
  return {
    ok: true,
    status: result.status,
    data: {
      sections: result.data.sections,
      errors: result.data.errors,
      tasks: result.data.tasks.map((t) => ({
        title: t.title,
        description: t.description,
        section: t.section,
        criticality: t.criticality,
        requiresPhoto: t.requires_photo,
        requiresComment: t.requires_comment,
      })),
    },
  };
}

export async function importTemplateApply(input: {
  name: string;
  roleTarget: UserRole;
  content: string;
}): Promise<ApiResult<ImportApplyResult>> {
  const result = await api.post<ImportApplyDTO>("/v1/templates/import", {
    name: input.name,
    role_target: input.roleTarget,
    content: input.content,
  });
  if (!result.ok) return result;
  return {
    ok: true,
    status: result.status,
    data: {
      templateId: result.data.template_id,
      sections: result.data.sections,
      taskCount: result.data.task_count,
    },
  };
}
