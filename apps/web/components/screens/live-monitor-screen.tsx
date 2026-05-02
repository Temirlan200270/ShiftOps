"use client";

/**
 * Live monitor screen — admin & owner only (S8).
 *
 * Anatomy
 * -------
 * - Top: connection-status pill ("Live / Reconnecting / Offline").
 * - Middle: list of active shifts. Each row updates progress bars and
 *   "critical pending" counters as ``task.completed`` events stream in.
 * - Bottom: rolling event feed (last 30) so admins see *what* changed,
 *   not just *that* something changed.
 *
 * Data flow
 * ---------
 * 1. Snapshot fetch on mount → seeds the shift list.
 * 2. WebSocket connects via ``useRealtimeStream``.
 * 3. Each event is reduced into local state — we don't requery the
 *    snapshot on every event because Supabase pooler is a precious
 *    resource. ``shift.opened`` adds a row, ``shift.closed`` removes,
 *    ``task.completed`` updates progress.
 * 4. The feed and the shift cards both use ``Date.now()`` for "x sec
 *    ago" rendering; we recompute every 15 s via ``useTick`` to avoid
 *    thrashing the React tree on every event arrival.
 */

import { ArrowLeft, ChevronRight, Radio, ShieldAlert, WifiOff } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import {
  fetchMonitorSnapshot,
  useRealtimeStream,
  type ActiveShift,
  type RealtimeEvent,
  type RealtimeStatus,
  type VacantAtRiskShift,
} from "@/lib/api/monitor";
import { toast } from "@/lib/stores/toast-store";
import { nowServerMs } from "@/lib/time/server-time";

interface LiveMonitorScreenProps {
  onBack: () => void;
}

type FeedItem = { id: string; at: number; key: string; values: Record<string, string> };

const FEED_MAX = 30;

function useTick(intervalMs: number): number {
  const [tick, setTick] = React.useState(() => nowServerMs());
  React.useEffect(() => {
    const id = setInterval(() => setTick(nowServerMs()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return tick;
}

function statusPill(status: RealtimeStatus, t: (key: string) => string): React.JSX.Element {
  if (status === "live") {
    return (
      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-success/15 text-success text-[11px] font-medium">
        <span className="relative flex size-2">
          <span className="absolute inline-flex h-full w-full rounded-full bg-success/50 animate-ping" />
          <span className="relative inline-flex rounded-full size-2 bg-success" />
        </span>
        {t("statusConnected")}
      </span>
    );
  }
  if (status === "reconnecting" || status === "connecting") {
    return (
      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-warning/15 text-warning text-[11px] font-medium">
        <Radio className="size-3 animate-pulse" />
        {t("statusReconnecting")}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-elevated text-muted-foreground text-[11px] font-medium">
      <WifiOff className="size-3" />
      {t("statusOffline")}
    </span>
  );
}

function formatRelative(ts: number, now: number): string {
  const diff = Math.max(0, Math.floor((now - ts) / 1000));
  if (diff < 60) return `${diff}s`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m`;
  return `${Math.floor(diff / 3600)}h`;
}

export function LiveMonitorScreen({ onBack }: LiveMonitorScreenProps): React.JSX.Element {
  const tLive = useTranslations("live");
  const tEv = useTranslations("live.events");
  const tErr = useTranslations("errors");

  const [shifts, setShifts] = React.useState<ActiveShift[]>([]);
  const [vacantAtRisk, setVacantAtRisk] = React.useState<VacantAtRiskShift[]>([]);
  const [feed, setFeed] = React.useState<FeedItem[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [lastEventAt, setLastEventAt] = React.useState<number | null>(null);
  const tick = useTick(15_000);

  // Snapshot: paint the screen instantly so admins don't see a blank
  // canvas while the WS handshake travels through Cloudflare.
  React.useEffect(() => {
    let alive = true;
    void (async () => {
      const result = await fetchMonitorSnapshot();
      if (!alive) return;
      setLoading(false);
      if (!result.ok) {
        toast({ variant: "critical", title: tErr("generic"), description: result.message });
        return;
      }
      setShifts(result.data.active);
      setVacantAtRisk(result.data.vacantAtRisk);
    })();
    return () => {
      alive = false;
    };
  }, [tErr]);

  // Reducer for the live event stream. We mutate local state rather
  // than re-fetch — see file header.
  const onEvent = React.useCallback(
    (event: RealtimeEvent) => {
      // Heartbeats and the initial hello aren't user-visible.
      if (event.type === "ping" || event.type === "hello") return;

      setLastEventAt(nowServerMs());

      if (event.type === "shift.opened") {
        const data = event.data as Extract<RealtimeEvent, { type: "shift.opened" }>["data"];
        setVacantAtRisk((prev) => prev.filter((v) => v.shiftId !== data.shift_id));
        setShifts((prev) => {
          if (prev.some((s) => s.shiftId === data.shift_id)) return prev;
          const next: ActiveShift = {
            shiftId: data.shift_id,
            locationId: data.location_id,
            locationName: data.location_name,
            templateName: data.template_name,
            operatorId: data.operator_id,
            operatorName: data.operator_name,
            scheduledStart: data.actual_start,
            scheduledEnd: data.actual_start,
            actualStart: data.actual_start,
            progressTotal: 0,
            progressDone: 0,
            progressCriticalPending: 0,
          };
          return [next, ...prev];
        });
        pushFeed(setFeed, {
          id: `o-${data.shift_id}`,
          key: "shiftOpened",
          values: { operator: data.operator_name, template: data.template_name },
        });
      } else if (event.type === "task.completed") {
        const data = event.data as Extract<RealtimeEvent, { type: "task.completed" }>["data"];
        setShifts((prev) =>
          prev.map((s) =>
            s.shiftId === data.shift_id
              ? {
                  ...s,
                  progressTotal: data.progress_total || s.progressTotal,
                  progressDone: data.progress_done || s.progressDone,
                  // We don't know the new critical-pending count from
                  // this event alone; if the task was critical and now
                  // done, decrement defensively (but never below zero).
                  progressCriticalPending:
                    data.criticality === "critical" && data.status === "done"
                      ? Math.max(0, s.progressCriticalPending - 1)
                      : s.progressCriticalPending,
                }
              : s,
          ),
        );
        const shift = findShift(data.shift_id);
        pushFeed(setFeed, {
          id: `t-${data.task_id}-${data.status}`,
          key: data.suspicious ? "taskSuspicious" : "taskCompleted",
          values: {
            operator: shift?.operatorName ?? data.location_name,
            title: data.template_task_title,
          },
        });
      } else if (event.type === "shift.closed") {
        const data = event.data as Extract<RealtimeEvent, { type: "shift.closed" }>["data"];
        setShifts((prev) => prev.filter((s) => s.shiftId !== data.shift_id));
        pushFeed(setFeed, {
          id: `c-${data.shift_id}`,
          key: "shiftClosed",
          values: { operator: data.operator_name, template: data.template_name },
        });
      } else if (event.type === "waiver.requested") {
        const data = event.data as Extract<RealtimeEvent, { type: "waiver.requested" }>["data"];
        pushFeed(setFeed, {
          id: `w-req-${data.task_id}`,
          key: "waiverRequested",
          values: { operator: data.operator_name, title: data.template_task_title },
        });
      } else if (event.type === "waiver.decided") {
        const data = event.data as Extract<RealtimeEvent, { type: "waiver.decided" }>["data"];
        pushFeed(setFeed, {
          id: `w-dec-${data.task_id}-${data.decision}`,
          key: "waiverDecided",
          values: { decision: data.decision, title: data.template_task_title },
        });
      }
      // Unknown event types: ignored. New backend events should not
      // crash older clients.

      function findShift(id: string): ActiveShift | undefined {
        // Closure capture is fine; React batches setShifts and our
        // shift list lives inside the same render tree.
        return shiftsRef.current.find((s) => s.shiftId === id);
      }
    },
    [],
  );

  // We only need a ref-based read of `shifts` from inside the event
  // handler so the closure stays stable; resubscribing the WS hook on
  // every state change would cancel the connection on every event.
  const shiftsRef = React.useRef<ActiveShift[]>([]);
  React.useEffect(() => {
    shiftsRef.current = shifts;
  }, [shifts]);

  const status = useRealtimeStream({ enabled: true, onEvent });

  return (
    <main className="mx-auto max-w-md px-4 pt-4 pb-24 animate-fade-in-up">
      <header className="flex items-center gap-3 mb-4">
        <Button variant="ghost" size="sm" onClick={onBack} className="-ml-2 px-2">
          <ArrowLeft className="size-5" />
        </Button>
        <div className="flex-1">
          <h1 className="text-lg font-semibold">{tLive("title")}</h1>
          <p className="text-xs text-muted-foreground">{tLive("subtitle")}</p>
        </div>
        {statusPill(status, tLive)}
      </header>

      {loading ? (
        <Card className="animate-pulse">
          <CardContent className="p-6 h-40" />
        </Card>
      ) : shifts.length === 0 && vacantAtRisk.length === 0 ? (
        <Card>
          <CardContent className="p-6 text-center">
            <p className="text-sm font-medium mb-1">{tLive("empty")}</p>
            <p className="text-xs text-muted-foreground">{tLive("emptyHint")}</p>
          </CardContent>
        </Card>
      ) : (
        <>
        {vacantAtRisk.length > 0 ? (
          <section className="mb-6">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-warning mb-2">
              {tLive("vacantTitle")}
            </h2>
            <p className="text-[11px] text-muted-foreground mb-2">{tLive("vacantSubtitle")}</p>
            <ul className="space-y-2">
              {vacantAtRisk.map((v) => (
                <li key={v.shiftId}>
                  <Card accent="warning">
                    <CardContent className="p-3">
                      <p className="text-sm font-medium">{v.templateName}</p>
                      <p className="text-[11px] text-muted-foreground">{v.locationName}</p>
                      <p className="text-[11px] text-muted-foreground mt-1">
                        {v.stationLabel
                          ? `${v.stationLabel} · slot ${v.slotIndex}`
                          : `slot ${v.slotIndex}`}
                      </p>
                      <p className="text-[11px] text-warning mt-1">
                        {tLive(`vacantKind.${v.kind}`)}
                      </p>
                      <p className="text-[10px] text-muted-foreground mt-1 tabular-nums">
                        {new Date(v.scheduledStart).toLocaleString()} →{" "}
                        {new Date(v.scheduledEnd).toLocaleTimeString()}
                      </p>
                    </CardContent>
                  </Card>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
        <ul className="space-y-2 mb-4">
          {shifts.map((shift) => {
            const total = Math.max(1, shift.progressTotal);
            const pct = Math.round((shift.progressDone / total) * 100);
            return (
              <li key={shift.shiftId}>
                <Card
                  accent={shift.progressCriticalPending > 0 ? "critical" : "none"}
                  className="overflow-hidden"
                >
                  <CardContent className="p-4">
                    <div className="flex items-center gap-3">
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium truncate">{shift.operatorName}</p>
                        <p className="text-xs text-muted-foreground truncate">
                          {shift.locationName} · {shift.templateName}
                        </p>
                      </div>
                      <div className="text-right shrink-0">
                        <p className="text-sm font-semibold tabular-nums">
                          {shift.progressDone}/{shift.progressTotal}
                        </p>
                        <p className="text-[10px] text-muted-foreground tabular-nums">{pct}%</p>
                      </div>
                      <ChevronRight className="size-4 text-muted-foreground shrink-0" />
                    </div>
                    <Progress value={pct} className="h-1.5 mt-3" />
                    {shift.progressCriticalPending > 0 ? (
                      <p className="text-[11px] text-critical mt-2 inline-flex items-center gap-1">
                        <ShieldAlert className="size-3" />
                        {tLive("criticalLeft", { count: shift.progressCriticalPending })}
                      </p>
                    ) : null}
                  </CardContent>
                </Card>
              </li>
            );
          })}
        </ul>
        </>
      )}

      {feed.length > 0 ? (
        <Card>
          <CardContent className="p-3">
            <p className="text-[10px] uppercase tracking-wide text-muted-foreground mb-2">
              {lastEventAt
                ? tLive("lastEventAt", { time: formatRelative(lastEventAt, tick) })
                : tLive("statusConnected")}
            </p>
            <ul className="space-y-1.5">
              {feed.map((item) => (
                <li
                  key={item.id}
                  className="text-xs flex items-baseline gap-2 leading-snug"
                >
                  <span className="text-[10px] text-muted-foreground tabular-nums w-8 shrink-0">
                    {formatRelative(item.at, tick)}
                  </span>
                  <span className="flex-1">{tEv(item.key, item.values)}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}
    </main>
  );
}

function pushFeed(
  setFeed: React.Dispatch<React.SetStateAction<FeedItem[]>>,
  item: Omit<FeedItem, "at">,
): void {
  setFeed((prev) => {
    const next = [{ ...item, at: nowServerMs() }, ...prev];
    if (next.length > FEED_MAX) next.length = FEED_MAX;
    return next;
  });
}
