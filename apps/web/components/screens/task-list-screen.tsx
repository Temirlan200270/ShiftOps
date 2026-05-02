"use client";

import { ArrowLeft, Camera, CheckCircle2, MessageSquareWarning, ShieldAlert } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { TaskDetailSheet } from "@/components/screens/task-detail-sheet";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { closeShift } from "@/lib/api/shifts";
import { localiseApiFailure } from "@/lib/i18n/api-errors";
import { usePreferencesStore } from "@/lib/stores/preferences-store";
import { useShiftStore } from "@/lib/stores/shift-store";
import { toast } from "@/lib/stores/toast-store";
import { authenticateShiftClose, isShiftCloseBiometricSupported } from "@/lib/telegram/biometric";
import { haptic, notify } from "@/lib/telegram/init";
import type { Criticality, TaskCard, TaskStatus } from "@/lib/types";

interface TaskListProps {
  onBack: () => void;
  onClosed: () => void;
}

const criticalityOrder: Record<Criticality, number> = {
  critical: 0,
  required: 1,
  optional: 2,
};

const statusOrder: Record<TaskStatus, number> = {
  pending: 0,
  waiver_pending: 1,
  waiver_rejected: 2,
  obsolete: 3,
  done: 4,
  waived: 5,
  skipped: 6,
};

function sortTasks(tasks: TaskCard[]): TaskCard[] {
  return [...tasks].sort((a, b) => {
    const sa = statusOrder[a.status];
    const sb = statusOrder[b.status];
    if (sa !== sb) return sa - sb;
    return criticalityOrder[a.criticality] - criticalityOrder[b.criticality];
  });
}

interface TaskGroup {
  section: string | null;
  tasks: TaskCard[];
}

/**
 * Group tasks by their section while preserving the order in which
 * sections first appear. Tasks without a section bubble up under a
 * `null` group rendered without a heading. Inside each group we keep
 * the same status/criticality sort the list used before — the visual
 * layering is identical to a flat list when no template uses sections.
 */
function groupTasks(tasks: TaskCard[]): TaskGroup[] {
  const groups = new Map<string | null, TaskCard[]>();
  for (const task of tasks) {
    const key = task.section ?? null;
    const existing = groups.get(key);
    if (existing) {
      existing.push(task);
    } else {
      groups.set(key, [task]);
    }
  }
  return Array.from(groups.entries()).map(([section, items]) => ({
    section,
    tasks: sortTasks(items),
  }));
}

function isDoneStatus(status: TaskStatus): boolean {
  return status === "done" || status === "waived";
}

function TaskRow({
  task,
  onOpen,
}: {
  task: TaskCard;
  onOpen: (id: string) => void;
}): React.JSX.Element {
  const tTasks = useTranslations("tasks");
  const isDone = task.status === "done" || task.status === "waived";
  const accent =
    task.criticality === "critical"
      ? "critical"
      : task.criticality === "required"
        ? "warning"
        : "none";

  return (
    <Card accent={accent} className="mb-2">
      <CardContent className="p-4">
        <button
          type="button"
          onClick={() => onOpen(task.id)}
          className="w-full flex items-center justify-between gap-3 text-left"
        >
          <div className="flex-1 min-w-0">
            <p
              className={`text-base font-medium truncate ${
                isDone ? "line-through text-muted-foreground" : ""
              }`}
            >
              {task.title}
            </p>
            <p className="text-xs text-muted-foreground mt-1 flex items-center gap-2 flex-wrap">
              <span>{tTasks(`criticality.${task.criticality}`)}</span>
              {task.requiresPhoto ? (
                <span className="inline-flex items-center gap-1">
                  · <Camera className="size-3" /> {tTasks("photoRequired")}
                </span>
              ) : null}
              {task.status === "waiver_pending" ? (
                <span className="text-warning">· {tTasks("status.waiver_pending")}</span>
              ) : null}
            </p>
          </div>
          {isDone ? (
            <CheckCircle2 className="size-6 text-success shrink-0" />
          ) : task.status === "waiver_pending" ? (
            <MessageSquareWarning className="size-6 text-warning shrink-0" />
          ) : task.criticality === "critical" ? (
            <ShieldAlert className="size-6 text-critical shrink-0" />
          ) : null}
        </button>
      </CardContent>
    </Card>
  );
}

export function TaskListScreen({ onBack, onClosed }: TaskListProps): React.JSX.Element {
  const shift = useShiftStore((s) => s.shift);
  const setShift = useShiftStore((s) => s.setShift);
  const [activeTaskId, setActiveTaskId] = React.useState<string | null>(null);
  const [closing, setClosing] = React.useState(false);
  const [confirmOpen, setConfirmOpen] = React.useState(false);
  const tDash = useTranslations("dashboard");
  const tClose = useTranslations("close");
  const tErr = useTranslations("errors");
  const biometricEnabled = usePreferencesStore((s) => s.shiftCloseBiometricEnabled);

  const allTasks = React.useMemo(() => sortTasks(shift?.tasks ?? []), [shift?.tasks]);
  const groups = React.useMemo(() => groupTasks(shift?.tasks ?? []), [shift?.tasks]);
  const hasSections = React.useMemo(
    () => groups.some((g) => g.section !== null),
    [groups],
  );
  const total = allTasks.length;
  const done = allTasks.filter((t) => isDoneStatus(t.status)).length;
  const progress = total === 0 ? 0 : Math.round((done / total) * 100);
  const criticalRemaining = allTasks.filter(
    (t) => t.criticality === "critical" && !isDoneStatus(t.status),
  ).length;
  const requiredMissing = allTasks.filter(
    (t) => t.criticality === "required" && !isDoneStatus(t.status),
  ).length;

  const [delayReason, setDelayReason] = React.useState("");

  const showDelayField = React.useMemo(() => {
    if (!shift) return false;
    return Date.now() > new Date(shift.scheduledEnd).getTime();
  }, [shift]);

  const handleClose = React.useCallback(
    async (confirmViolations: boolean) => {
      if (!shift) return;

      if (biometricEnabled && isShiftCloseBiometricSupported()) {
        const ok = await authenticateShiftClose(tClose("biometricReason"));
        if (!ok) {
          toast({ variant: "default", title: tClose("biometricCancelled") });
          return;
        }
      }

      setClosing(true);
      const result = await closeShift({
        shiftId: shift.id,
        confirmViolations,
        delayReason: showDelayField ? delayReason.trim() || null : null,
      });
      setClosing(false);
      if (result.ok) {
        // Merge the close-time delta onto the in-memory shift so the summary
        // screen can render the breakdown without an extra fetch.
        setShift({
          ...shift,
          status: result.data.finalStatus,
          score: result.data.score,
          scoreBreakdown: result.data.breakdown,
          formulaVersion: result.data.formulaVersion,
          actualEnd: new Date().toISOString(),
        });
        notify("success");
        setConfirmOpen(false);
        onClosed();
        return;
      }
      if (result.code === "required_tasks_missed_confirm_required") {
        setConfirmOpen(true);
        return;
      }
      if (result.code === "critical_tasks_pending") {
        notify("error");
        toast({ variant: "critical", title: tErr("criticalBlocked") });
        return;
      }
      notify("error");
      toast({
        variant: "critical",
        title: tErr("generic"),
        description: localiseApiFailure(result, tErr),
      });
    },
    [shift, setShift, onClosed, tErr, biometricEnabled, tClose, showDelayField, delayReason],
  );

  if (!shift) return <></>;

  const closeBlocked = criticalRemaining > 0;

  return (
    <main className="mx-auto max-w-md px-4 pt-4 pb-32">
      <header className="flex items-center gap-3 mb-4">
        <Button variant="ghost" size="sm" onClick={onBack} className="-ml-2 px-2">
          <ArrowLeft className="size-5" />
        </Button>
        <div className="flex-1">
          <h1 className="text-lg font-semibold">{shift.templateName}</h1>
          {shift.stationLabel ? (
            <p className="text-[11px] text-muted-foreground">
              {tDash("stationLabel", { label: shift.stationLabel })} ·{" "}
              {tDash("slotIndexShort", { index: shift.slotIndex })}
            </p>
          ) : (
            <p className="text-[11px] text-muted-foreground">
              {tDash("slotIndexShort", { index: shift.slotIndex })}
            </p>
          )}
          <p className="text-[11px] text-muted-foreground">{tDash("operatorOnShift", { name: shift.operatorFullName })}</p>
          <p className="text-xs text-muted-foreground">
            {done}/{total} · {progress}%
          </p>
        </div>
      </header>

      <Progress value={progress} className="mb-4" />

      {showDelayField ? (
        <div className="mb-4 space-y-2">
          <p className="text-xs text-muted-foreground">{tClose("delayReasonHint")}</p>
          <label className="block text-sm font-medium" htmlFor="shift-delay-reason">
            {tClose("delayReasonLabel")}
          </label>
          <textarea
            id="shift-delay-reason"
            className="w-full min-h-[72px] rounded-md border border-border bg-background px-3 py-2 text-sm"
            value={delayReason}
            onChange={(e) => setDelayReason(e.target.value)}
            placeholder={tClose("delayReasonPlaceholder")}
            maxLength={500}
            rows={3}
          />
        </div>
      ) : null}

      {hasSections
        ? groups.map((group) => (
            <SectionGroup
              key={group.section ?? "__no_section__"}
              group={group}
              onOpen={setActiveTaskId}
            />
          ))
        : allTasks.map((task) => (
            <TaskRow key={task.id} task={task} onOpen={setActiveTaskId} />
          ))}

      <div className="fixed inset-x-0 bottom-0 px-4 pt-2 pb-[calc(0.75rem+env(safe-area-inset-bottom))] bg-background/95 backdrop-blur border-t border-border">
        <div className="mx-auto max-w-md">
          <Button
            size="block"
            variant={closeBlocked ? "secondary" : "primary"}
            disabled={closeBlocked || closing}
            onClick={() => {
              haptic("heavy");
              if (requiredMissing > 0) setConfirmOpen(true);
              else void handleClose(false);
            }}
          >
            {tClose("cta")}
          </Button>
          {closeBlocked ? (
            <p className="text-xs text-critical mt-2 text-center">{tClose("blockedBody")}</p>
          ) : null}
        </div>
      </div>

      <Sheet open={confirmOpen} onOpenChange={setConfirmOpen}>
        <SheetTrigger asChild>
          <span hidden />
        </SheetTrigger>
        <SheetContent title={tClose("warningTitle")}>
          <p className="text-sm text-muted-foreground mb-4">
            {tClose("warningBody", { count: requiredMissing })}
          </p>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              size="block"
              onClick={() => setConfirmOpen(false)}
              disabled={closing}
            >
              {tClose("cancel")}
            </Button>
            <Button
              variant="danger"
              size="block"
              onClick={() => void handleClose(true)}
              disabled={closing}
            >
              {tClose("confirm")}
            </Button>
          </div>
        </SheetContent>
      </Sheet>

      <TaskDetailSheet
        taskId={activeTaskId}
        onClose={() => setActiveTaskId(null)}
      />
    </main>
  );
}

/**
 * One section worth of tasks. Header shows the human label, completion
 * counter, and a tiny dot when the section still has critical tasks
 * pending. We deliberately do not collapse sections by default — the
 * operator wants every group at-a-glance and we already have a global
 * progress bar at the top.
 */
function SectionGroup({
  group,
  onOpen,
}: {
  group: TaskGroup;
  onOpen: (id: string) => void;
}): React.JSX.Element {
  const total = group.tasks.length;
  const done = group.tasks.filter((t) => isDoneStatus(t.status)).length;
  const criticalLeft = group.tasks.filter(
    (t) => t.criticality === "critical" && !isDoneStatus(t.status),
  ).length;
  const ratio = total === 0 ? 0 : done / total;

  return (
    <section className="mb-4">
      {group.section !== null ? (
        <header className="flex items-center justify-between mb-2 px-1">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {group.section}
          </h2>
          <span className="text-[11px] text-muted-foreground tabular-nums">
            {done}/{total}
            {criticalLeft > 0 ? <span className="text-critical ml-2">●</span> : null}
          </span>
        </header>
      ) : null}
      <div
        className="h-1 mb-2 rounded-full bg-elevated overflow-hidden"
        aria-hidden
        style={{ display: group.section === null ? "none" : "block" }}
      >
        <div
          className="h-full bg-primary"
          style={{ width: `${Math.round(ratio * 100)}%` }}
        />
      </div>
      {group.tasks.map((task) => (
        <TaskRow key={task.id} task={task} onOpen={onOpen} />
      ))}
    </section>
  );
}
