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
  criticality: Criticality;
  requiresPhoto: boolean;
  requiresComment: boolean;
  orderIndex: number;
}

export interface TemplateDetail {
  id: string;
  name: string;
  roleTarget: UserRole;
  tasks: TemplateTaskRow[];
}

export interface TemplateTaskInput {
  // Optional id: present when editing an existing task to preserve its
  // primary key; omitted/null for fresh rows.
  id: string | null;
  title: string;
  description: string | null;
  criticality: Criticality;
  requiresPhoto: boolean;
  requiresComment: boolean;
}

export interface TemplateInput {
  name: string;
  roleTarget: UserRole;
  tasks: TemplateTaskInput[];
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
  criticality: Criticality;
  requires_photo: boolean;
  requires_comment: boolean;
  order_index: number;
}

interface DetailDTO {
  id: string;
  name: string;
  role_target: UserRole;
  tasks: TaskDTO[];
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
      criticality: t.criticality,
      requires_photo: t.requiresPhoto,
      requires_comment: t.requiresComment,
    })),
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
