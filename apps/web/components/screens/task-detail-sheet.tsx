"use client";

import { Camera, Images, Loader2, RotateCcw, ShieldQuestion, X } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { completeTask, requestWaiver } from "@/lib/api/shifts";
import { enqueuePhotoUpload } from "@/lib/offline/queue";
import { useShiftStore } from "@/lib/stores/shift-store";
import { toast } from "@/lib/stores/toast-store";
import {
  cloudStorageGet,
  cloudStorageRemove,
  cloudStorageSet,
  isCloudStorageAvailable,
  taskCommentDraftKey,
  taskWaiverDraftKey,
} from "@/lib/telegram/cloud-storage";
import { haptic, notify } from "@/lib/telegram/init";

async function compressImage(file: File, maxW = 1600, quality = 0.82): Promise<Blob> {
  return new Promise((resolve) => {
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      URL.revokeObjectURL(url);
      const scale = Math.min(1, maxW / img.naturalWidth);
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(img.naturalWidth * scale);
      canvas.height = Math.round(img.naturalHeight * scale);
      const ctx = canvas.getContext("2d");
      if (!ctx) { resolve(file); return; }
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      canvas.toBlob((blob) => resolve(blob ?? file), "image/jpeg", quality);
    };
    img.onerror = () => { URL.revokeObjectURL(url); resolve(file); };
    img.src = url;
  });
}

interface TaskDetailSheetProps {
  taskId: string | null;
  onClose: () => void;
}

export function TaskDetailSheet({ taskId, onClose }: TaskDetailSheetProps): React.JSX.Element {
  const shift = useShiftStore((s) => s.shift);
  const markOptimistic = useShiftStore((s) => s.markTaskOptimistic);
  const cameraInputRef = React.useRef<HTMLInputElement>(null);
  const galleryInputRef = React.useRef<HTMLInputElement>(null);
  const [photo, setPhoto] = React.useState<Blob | null>(null);
  const [photoUrl, setPhotoUrl] = React.useState<string | null>(null);
  const [comment, setComment] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [waiverMode, setWaiverMode] = React.useState(false);
  const [waiverReason, setWaiverReason] = React.useState("");
  const [draftReady, setDraftReady] = React.useState(false);
  const tTasks = useTranslations("tasks");
  const tErr = useTranslations("errors");

  const task = React.useMemo(
    () => shift?.tasks.find((t) => t.id === taskId) ?? null,
    [shift?.tasks, taskId],
  );

  React.useEffect(() => {
    if (!photo) { setPhotoUrl(null); return; }
    const url = URL.createObjectURL(photo);
    setPhotoUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [photo]);

  React.useEffect(() => {
    if (!taskId) {
      setDraftReady(false);
      setPhoto(null);
      setComment("");
      setWaiverMode(false);
      setWaiverReason("");
      return;
    }

    setDraftReady(false);
    setPhoto(null);
    setWaiverMode(false);
    setComment("");
    setWaiverReason("");

    if (!isCloudStorageAvailable()) {
      setDraftReady(true);
      return;
    }

    let cancelled = false;
    void (async () => {
      const [c, w] = await Promise.all([
        cloudStorageGet(taskCommentDraftKey(taskId)),
        cloudStorageGet(taskWaiverDraftKey(taskId)),
      ]);
      if (cancelled) return;
      if (c) setComment(c);
      if (w) setWaiverReason(w);
      setDraftReady(true);
    })();

    return () => {
      cancelled = true;
    };
  }, [taskId]);

  React.useEffect(() => {
    if (!taskId || !draftReady || !isCloudStorageAvailable()) return;
    const t = window.setTimeout(() => {
      void cloudStorageSet(taskCommentDraftKey(taskId), comment);
    }, 480);
    return () => window.clearTimeout(t);
  }, [comment, taskId, draftReady]);

  React.useEffect(() => {
    if (!taskId || !draftReady || !isCloudStorageAvailable()) return;
    const t = window.setTimeout(() => {
      void cloudStorageSet(taskWaiverDraftKey(taskId), waiverReason);
    }, 480);
    return () => window.clearTimeout(t);
  }, [waiverReason, taskId, draftReady]);

  const handleTakePhoto = React.useCallback(() => {
    cameraInputRef.current?.click();
  }, []);

  const handlePickFromGallery = React.useCallback(() => {
    galleryInputRef.current?.click();
  }, []);

  const handleRemovePhoto = React.useCallback(() => {
    setPhoto(null);
    haptic("light");
  }, []);

  const handleFileChange = React.useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.currentTarget.value = "";
    if (!file) return;
    haptic("light");
    void compressImage(file).then(setPhoto);
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
      void cloudStorageRemove(taskCommentDraftKey(task.id));
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
      void cloudStorageRemove(taskCommentDraftKey(task.id));
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
      void cloudStorageRemove(taskWaiverDraftKey(task.id));
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

              {/* Photo capture area */}
              {photoUrl ? (
                <div className="relative mb-3 rounded-xl overflow-hidden bg-elevated">
                  <img
                    src={photoUrl}
                    alt=""
                    className="w-full max-h-52 object-cover"
                  />
                  <div className="absolute inset-x-0 bottom-0 flex items-center justify-between px-3 py-2.5 bg-gradient-to-t from-black/65 to-transparent">
                    <button
                      type="button"
                      onClick={handleTakePhoto}
                      disabled={submitting}
                      className="inline-flex items-center gap-1.5 text-xs font-medium text-white/90 active:text-white"
                    >
                      <RotateCcw className="size-3.5" />
                      {tTasks("retakePhoto")}
                    </button>
                    <button
                      type="button"
                      onClick={handleRemovePhoto}
                      disabled={submitting}
                      className="inline-flex items-center gap-1.5 text-xs font-medium text-white/90 active:text-white"
                    >
                      <X className="size-3.5" />
                      {tTasks("removePhoto")}
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-1 mb-3">
                  <Button
                    variant="secondary"
                    size="block"
                    onClick={handleTakePhoto}
                    disabled={submitting}
                  >
                    <Camera className="size-5" />
                    {tTasks("takePhoto")}
                  </Button>
                  <button
                    type="button"
                    onClick={handlePickFromGallery}
                    disabled={submitting}
                    className="inline-flex items-center gap-1.5 py-1 text-sm text-muted-foreground active:text-foreground"
                  >
                    <Images className="size-3.5" />
                    {tTasks("pickFromGallery")}
                  </button>
                </div>
              )}

              <input
                ref={cameraInputRef}
                type="file"
                accept="image/*"
                capture="environment"
                hidden
                onChange={handleFileChange}
              />
              <input
                ref={galleryInputRef}
                type="file"
                accept="image/*"
                hidden
                onChange={handleFileChange}
              />

              <textarea
                placeholder={tTasks("addComment")}
                className="w-full min-h-[80px] rounded-md bg-elevated p-3 text-sm border border-border focus:outline-none focus:ring-2 focus:ring-ring mb-3"
                value={comment}
                onChange={(e) => setComment(e.target.value)}
              />

              <Button size="block" onClick={handleSubmit} disabled={submitting} className="mb-2">
                {submitting ? <Loader2 className="size-5 animate-spin" /> : null}
                {tTasks("markDone")}
              </Button>

              {!task.requiresPhoto && !photo ? (
                <button
                  type="button"
                  onClick={handleSubmit}
                  disabled={submitting}
                  className="w-full py-1 text-sm text-muted-foreground active:text-foreground"
                >
                  {tTasks("markDoneNoPhoto")}
                </button>
              ) : null}

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
