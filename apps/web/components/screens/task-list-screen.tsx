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
import { useShiftStore } from "@/lib/stores/shift-store";
import { toast } from "@/lib/stores/toast-store";
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
  done: 3,
  waived: 4,
  skipped: 5,
};

function sortTasks(tasks: TaskCard[]): TaskCard[] {
  return [...tasks].sort((a, b) => {
    const sa = statusOrder[a.status];
    const sb = statusOrder[b.status];
    if (sa !== sb) return sa - sb;
    return criticalityOrder[a.criticality] - criticalityOrder[b.criticality];
  });
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
  const tClose = useTranslations("close");
  const tErr = useTranslations("errors");

  const tasks = React.useMemo(() => sortTasks(shift?.tasks ?? []), [shift?.tasks]);
  const total = tasks.length;
  const done = tasks.filter((t) => t.status === "done" || t.status === "waived").length;
  const progress = total === 0 ? 0 : Math.round((done / total) * 100);
  const criticalRemaining = tasks.filter(
    (t) =>
      t.criticality === "critical" &&
      t.status !== "done" &&
      t.status !== "waived",
  ).length;
  const requiredMissing = tasks.filter(
    (t) =>
      t.criticality === "required" &&
      t.status !== "done" &&
      t.status !== "waived",
  ).length;

  const handleClose = React.useCallback(
    async (confirmViolations: boolean) => {
      if (!shift) return;
      setClosing(true);
      const result = await closeShift({ shiftId: shift.id, confirmViolations });
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
      toast({ variant: "critical", title: tErr("generic"), description: result.message });
    },
    [shift, setShift, onClosed, tErr],
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
          <p className="text-xs text-muted-foreground">
            {done}/{total} · {progress}%
          </p>
        </div>
      </header>

      <Progress value={progress} className="mb-4" />

      {tasks.map((task) => (
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
