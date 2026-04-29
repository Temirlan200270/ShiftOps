"use client";

import { api, type ApiResult } from "@/lib/api/client";

export interface AuditEventRow {
  id: string;
  createdAt: string;
  eventType: string;
  actorUserId: string | null;
  actorName: string | null;
  payload: Record<string, unknown>;
}

export interface AuditPage {
  items: AuditEventRow[];
  nextCursor: string | null;
}

interface AuditEventDTO {
  id: string;
  created_at: string;
  event_type: string;
  actor_user_id: string | null;
  actor_name: string | null;
  payload: Record<string, unknown>;
}

interface AuditPageDTO {
  items: AuditEventDTO[];
  next_cursor: string | null;
}

function fromDto(dto: AuditEventDTO): AuditEventRow {
  return {
    id: dto.id,
    createdAt: dto.created_at,
    eventType: dto.event_type,
    actorUserId: dto.actor_user_id,
    actorName: dto.actor_name,
    payload: dto.payload ?? {},
  };
}

export async function fetchAuditEvents(input: {
  cursor?: string | null;
  limit?: number;
  eventType?: string | null;
} = {}): Promise<ApiResult<AuditPage>> {
  const params = new URLSearchParams();
  if (input.cursor) params.set("cursor", input.cursor);
  if (input.limit) params.set("limit", String(input.limit));
  if (input.eventType) params.set("event_type", input.eventType);
  const qs = params.toString();
  const result = await api.get<AuditPageDTO>(`/v1/audit/events${qs ? `?${qs}` : ""}`);
  if (!result.ok) return result;
  return {
    ok: true,
    status: result.status,
    data: {
      items: result.data.items.map(fromDto),
      nextCursor: result.data.next_cursor,
    },
  };
}

