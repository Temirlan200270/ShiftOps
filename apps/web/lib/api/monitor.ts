"use client";

/**
 * Live monitor client = HTTP snapshot + a thin WebSocket hook.
 *
 * Why a custom hook instead of pulling in a socket library
 * --------------------------------------------------------
 * Per project rules we keep dependencies small. This file owns three
 * things:
 *
 * 1. ``fetchActiveShifts`` — REST snapshot used to paint the screen the
 *    moment it opens, so admins don't stare at "Connecting…".
 * 2. ``useRealtimeStream`` — wraps the native ``WebSocket`` API with
 *    automatic exponential reconnect (capped) and a status state so
 *    the UI can render "Live / Reconnecting / Offline".
 * 3. The ``RealtimeEvent`` discriminated union, mirrored exactly from
 *    the Python side (``infra/realtime/event_bus.py``).
 *
 * If we ever migrate to SSE or to a proper realtime SaaS, only this
 * file changes; consumer screens treat the hook as a black box.
 */

import * as React from "react";

import { api, type ApiResult } from "@/lib/api/client";
import { useAuthStore } from "@/lib/stores/auth-store";

export interface ActiveShift {
  shiftId: string;
  locationId: string;
  locationName: string;
  templateName: string;
  operatorId: string;
  operatorName: string;
  scheduledStart: string;
  scheduledEnd: string;
  actualStart: string | null;
  progressTotal: number;
  progressDone: number;
  progressCriticalPending: number;
}

interface ActiveShiftDTO {
  shift_id: string;
  location_id: string;
  location_name: string;
  template_name: string;
  operator_id: string;
  operator_name: string;
  scheduled_start: string;
  scheduled_end: string;
  actual_start: string | null;
  progress_total: number;
  progress_done: number;
  progress_critical_pending: number;
}

export async function fetchActiveShifts(): Promise<ApiResult<ActiveShift[]>> {
  const result = await api.get<ActiveShiftDTO[]>("/v1/realtime/active-shifts");
  if (!result.ok) return result;
  return {
    ok: true,
    status: result.status,
    data: result.data.map((dto) => ({
      shiftId: dto.shift_id,
      locationId: dto.location_id,
      locationName: dto.location_name,
      templateName: dto.template_name,
      operatorId: dto.operator_id,
      operatorName: dto.operator_name,
      scheduledStart: dto.scheduled_start,
      scheduledEnd: dto.scheduled_end,
      actualStart: dto.actual_start,
      progressTotal: dto.progress_total,
      progressDone: dto.progress_done,
      progressCriticalPending: dto.progress_critical_pending,
    })),
  };
}

// All event payloads we care about on the wire. The server can always
// add new types — unknown types are no-ops for older clients, which is
// exactly what we want for a forward-compatible streaming protocol.
export type RealtimeEvent =
  | { type: "hello"; data: { organization_id: string; role: string; server_time: string } }
  | { type: "ping"; data: { at: string } }
  | {
      type: "shift.opened";
      data: {
        shift_id: string;
        location_id: string;
        location_name: string;
        template_name: string;
        operator_id: string;
        operator_name: string;
        actual_start: string;
      };
    }
  | {
      type: "shift.closed";
      data: {
        shift_id: string;
        location_id: string;
        location_name: string;
        template_name: string;
        operator_id: string;
        operator_name: string;
        actual_end: string;
        score: number | null;
        status: "closed_clean" | "closed_with_violations";
      };
    }
  | {
      type: "task.completed";
      data: {
        shift_id: string;
        task_id: string;
        location_name: string;
        template_task_title: string;
        criticality: "critical" | "required" | "optional";
        status: string;
        suspicious: boolean;
        progress_total: number;
        progress_done: number;
      };
    }
  | {
      type: "task.suspicious";
      data: {
        shift_id: string;
        task_id: string;
        location_name: string;
        template_task_title: string;
        operator_name: string;
      };
    }
  | {
      type: "waiver.requested";
      data: {
        shift_id: string;
        task_id: string;
        operator_name: string;
        template_task_title: string;
        reason: string;
      };
    }
  | {
      type: "waiver.decided";
      data: {
        shift_id: string;
        task_id: string;
        decision: "approved" | "rejected";
        template_task_title: string;
      };
    }
  | { type: string; data: Record<string, unknown> };

export type RealtimeStatus = "connecting" | "live" | "reconnecting" | "offline";

interface UseRealtimeStreamOptions {
  enabled: boolean;
  onEvent: (event: RealtimeEvent) => void;
}

const WS_BASE = ((): string => {
  const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "";
  if (!apiBase) {
    if (typeof window === "undefined") return "";
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.host}/api`;
  }
  if (apiBase.startsWith("https://")) return `wss://${apiBase.slice("https://".length)}`;
  if (apiBase.startsWith("http://")) return `ws://${apiBase.slice("http://".length)}`;
  // Same-origin (e.g. "/api"). Browser only.
  if (typeof window === "undefined") return apiBase;
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${apiBase}`;
})();

const _MAX_BACKOFF_MS = 15_000;

/**
 * Connects to the realtime stream and forwards events through the
 * caller-provided callback. We deliberately keep events out of state
 * here: a list of events should live in the consumer (subject to UX
 * decisions — cap, dedupe, group). The hook owns *connection*, not
 * *content*.
 */
export function useRealtimeStream(opts: UseRealtimeStreamOptions): RealtimeStatus {
  const { enabled, onEvent } = opts;
  const [status, setStatus] = React.useState<RealtimeStatus>("offline");

  // Refs so the inner reconnect loop never sees stale closures.
  const onEventRef = React.useRef(onEvent);
  React.useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);

  React.useEffect(() => {
    if (!enabled) {
      setStatus("offline");
      return;
    }
    if (typeof window === "undefined") return;

    let cancelled = false;
    let ws: WebSocket | null = null;
    let attempt = 0;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const connect = (): void => {
      const token = useAuthStore.getState().accessToken;
      if (!token) {
        setStatus("offline");
        return;
      }
      setStatus(attempt === 0 ? "connecting" : "reconnecting");
      const url = `${WS_BASE}/v1/realtime/ws?token=${encodeURIComponent(token)}`;
      try {
        ws = new WebSocket(url);
      } catch {
        scheduleReconnect();
        return;
      }

      ws.onopen = () => {
        if (cancelled) return;
        attempt = 0;
        setStatus("live");
      };

      ws.onmessage = (msg: MessageEvent) => {
        if (cancelled) return;
        if (typeof msg.data !== "string") return;
        try {
          const parsed = JSON.parse(msg.data) as RealtimeEvent;
          onEventRef.current(parsed);
        } catch {
          // Malformed frame — ignore. The server JSON-encodes everything,
          // so this only fires under proxy corruption, in which case
          // dropping the frame is the right thing to do.
        }
      };

      ws.onerror = () => {
        // The browser also fires `onclose` after `onerror`; do nothing
        // here to avoid scheduling two reconnects.
      };

      ws.onclose = () => {
        if (cancelled) return;
        scheduleReconnect();
      };
    };

    const scheduleReconnect = (): void => {
      if (cancelled) return;
      setStatus("reconnecting");
      attempt += 1;
      // Exponential backoff with full jitter — caps at MAX_BACKOFF_MS.
      const base = Math.min(_MAX_BACKOFF_MS, 500 * 2 ** attempt);
      const delay = Math.floor(Math.random() * base);
      reconnectTimer = setTimeout(connect, delay);
    };

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (ws) {
        ws.onclose = null;
        ws.onerror = null;
        ws.onmessage = null;
        ws.onopen = null;
        try {
          ws.close();
        } catch {
          // already closed
        }
      }
      setStatus("offline");
    };
  }, [enabled]);

  return status;
}
