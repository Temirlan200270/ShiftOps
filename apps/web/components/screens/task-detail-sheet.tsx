"use client";

import { Camera, Loader2, ShieldQuestion } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { completeTask, requestWaiver } from "@/lib/api/shifts";
import { useShiftStore } from "@/lib/stores/shift-store";
import { toast } from "@/lib/stores/toast-store";
import { haptic, notify } from "@/lib/telegram/init";
import { enqueuePhotoUpload } from "@/lib/offline/queue";

interface TaskDetailSheetProps {
  taskId: string | null;
  onClose: () => void;
}

export function TaskDetailSheet({ taskId, onClose }: TaskDetailSheetProps): React.JSX.Element {
  const shift = useShiftStore((s) => s.shift);
  const markOptimistic = useShiftStore((s) => s.markTaskOptimistic);
  const fileInputRef = React.useRef<HTMLInputElement>(null);
  const [photo, setPhoto] = React.useState<Blob | null>(null);
  const [comment, setComment] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [waiverMode, setWaiverMode] = React.useState(false);
  const [waiverReason, setWaiverReason] = React.useState("");
  const tTasks = useTranslations("tasks");
  const tErr = useTranslations("errors");

  const task = React.useMemo(
    () => shift?.tasks.find((t) => t.id === taskId) ?? null,
    [shift?.tasks, taskId],
  );

  React.useEffect(() => {
    if (!taskId) {
      setPhoto(null);
      setComment("");
      setWaiverMode(false);
      setWaiverReason("");
    }
  }, [taskId]);

  const handlePickPhoto = React.useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const handleFileChange = React.useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setPhoto(file);
      haptic("light");
    }
  }, []);

  const handleSubmit = React.useCallback(async () => {
    if (!task) return;
    if (task.requiresPhoto && !photo) {
      toast({ variant: "warning", title: tTasks("photoRequired") });
      return;
    }
    if (task.requiresComment && !comment.trim()) {
      toast({ variant: "warning", title: tTasks("commentRequired") });
      return;
    }

    setSubmitting(true);
    markOptimistic(task.id, { status: "done" });

    if (!navigator.onLine && photo) {
      await enqueuePhotoUpload({ taskId: task.id, photo, comment });
      toast({ variant: "default", title: tErr("uploadRetrying") });
      setSubmitting(false);
      onClose();
      return;
    }

    const payload: { taskId: string; photo?: Blob; comment?: string } = { taskId: task.id };
    if (photo) payload.photo = photo;
    if (comment.trim()) payload.comment = comment.trim();
    const result = await completeTask(payload);
    setSubmitting(false);

    if (result.ok) {
      notify("success");
      if (result.data.suspicious) {
        toast({ variant: "warning", title: tTasks("suspiciousFlagged") });
      }
      onClose();
    } else {
      notify("error");
      markOptimistic(task.id, { status: "pending" });
      toast({ variant: "critical", title: tErr("generic"), description: result.message });
    }
  }, [task, photo, comment, markOptimistic, onClose, tTasks, tErr]);

  const handleWaiverSubmit = React.useCallback(async () => {
    if (!task) return;
    if (waiverReason.trim().length < 4) {
      toast({ variant: "warning", title: tTasks("waiverReason") });
      return;
    }
    setSubmitting(true);
    markOptimistic(task.id, { status: "waiver_pending" });
    const result = await requestWaiver({ taskId: task.id, reason: waiverReason.trim() });
    setSubmitting(false);
    if (result.ok) {
      notify("success");
      toast({ variant: "default", title: tTasks("waiverPendingHint") });
      onClose();
    } else {
      notify("error");
      markOptimistic(task.id, { status: "pending" });
      toast({ variant: "critical", title: tErr("generic"), description: result.message });
    }
  }, [task, waiverReason, markOptimistic, onClose, tTasks, tErr]);

  return (
    <Sheet
      open={Boolean(taskId)}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <SheetContent title={task?.title ?? ""}>
        {task ? (
          waiverMode ? (
            <>
              <p className="text-sm text-muted-foreground mb-3">{tTasks("waiverReason")}</p>
              <textarea
                className="w-full min-h-[120px] rounded-md bg-elevated p-3 text-sm border border-border focus:outline-none focus:ring-2 focus:ring-ring"
                value={waiverReason}
                onChange={(e) => setWaiverReason(e.target.value)}
              />
              <div className="flex gap-2 mt-4">
                <Button variant="secondary" size="block" onClick={() => setWaiverMode(false)}>
                  ←
                </Button>
                <Button
                  variant="warning"
                  size="block"
                  onClick={handleWaiverSubmit}
                  disabled={submitting}
                >
                  {tTasks("waiverSubmit")}
                </Button>
              </div>
            </>
          ) : (
            <>
              {task.description ? (
                <p className="text-sm text-muted-foreground mb-3">{task.description}</p>
              ) : null}

              {task.requiresPhoto ? (
                <Button
                  variant={photo ? "success" : "secondary"}
                  size="block"
                  onClick={handlePickPhoto}
                  disabled={submitting}
                  className="mb-3"
                >
                  <Camera className="size-5" />
                  {photo ? `✓ ${tTasks("takePhoto")}` : tTasks("takePhoto")}
                </Button>
              ) : null}

              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                capture="environment"
                hidden
                onChange={handleFileChange}
              />

              <textarea
                placeholder={tTasks("addComment")}
                className="w-full min-h-[80px] rounded-md bg-elevated p-3 text-sm border border-border focus:outline-none focus:ring-2 focus:ring-ring mb-3"
                value={comment}
                onChange={(e) => setComment(e.target.value)}
              />

              <Button size="block" onClick={handleSubmit} disabled={submitting}>
                {submitting ? <Loader2 className="size-5 animate-spin" /> : null}
                {tTasks("markDone")}
              </Button>

              <button
                type="button"
                onClick={() => setWaiverMode(true)}
                className="mt-3 w-full inline-flex items-center justify-center gap-2 text-sm text-muted-foreground hover:text-foreground"
                disabled={submitting}
              >
                <ShieldQuestion className="size-4" />
                {tTasks("requestWaiver")}
              </button>
            </>
          )
        ) : null}
      </SheetContent>
    </Sheet>
  );
}
