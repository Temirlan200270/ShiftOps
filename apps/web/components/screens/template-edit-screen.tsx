"use client";

import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  AlertTriangle,
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  Camera,
  ClipboardPaste,
  GripVertical,
  MessageSquare,
  Plus,
  Save,
  Trash2,
} from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import {
  createTemplate,
  deleteTemplate,
  getTemplate,
  importTemplateApply,
  importTemplateDryRun,
  updateTemplate,
  type ImportPreview,
  type RecurrenceConfig,
  type TemplateTaskInput,
} from "@/lib/api/templates";
import { fetchLocations, fetchTeamMembers, type LocationRow, type TeamMemberRow } from "@/lib/api/invites";
import { toast } from "@/lib/stores/toast-store";
import { haptic, notify } from "@/lib/telegram/init";
import type { Criticality, UserRole } from "@/lib/types";

interface TemplateEditScreenProps {
  templateId: string | null;
  onBack: () => void;
  onSaved: () => void;
}

/**
 * S7 editor — name + role + ordered task list.
 *
 * Reorder UX
 * ----------
 * We use `@dnd-kit/sortable` for pointer- and keyboard-driven
 * reordering. The library is ~30 KB gzipped which is steeper than the
 * "couple of buttons" alternative, but in exchange we get:
 *
 * - Touch + pointer + keyboard input out of the box (TWA on iOS works).
 * - Screen-reader announcements for picked-up / dropped items.
 * - FLIP-style animations without us hand-rolling them.
 *
 * The `↑` / `↓` buttons are intentionally kept as a fallback affordance:
 * they are discoverable on first sight and give a non-DnD path if a
 * user is on a flaky network and the dnd-kit chunk fails to load. They
 * are duplicates of the keyboard sensor in normal flows; that's fine.
 *
 * Data shape is unchanged: the server reads task order from the array
 * position, so swapping the UI from buttons to DnD is a no-op for the
 * API contract.
 *
 * Validation
 * ----------
 * Mirrors the Pydantic constraints on the server (3..128 chars name,
 * 1..200 tasks, 3..255 char titles). Server validation is still the
 * source of truth — we just shave one round-trip on common typos.
 */
type DraftTask = TemplateTaskInput & { localKey: string };

const CRITICALITIES: ReadonlyArray<Criticality> = ["critical", "required", "optional"];
const ROLE_TARGETS: ReadonlyArray<UserRole> = ["operator", "admin", "bartender"];

function memberAssignableForRoleTarget(roleTarget: UserRole, memberRole: string): boolean {
  if (roleTarget === "admin") return memberRole === "admin" || memberRole === "owner";
  if (roleTarget === "bartender")
    return memberRole === "bartender" || memberRole === "admin" || memberRole === "owner";
  return true;
}

function makeLocalKey(): string {
  return `local-${Math.random().toString(36).slice(2, 10)}`;
}

function emptyTask(): DraftTask {
  return {
    id: null,
    title: "",
    description: null,
    section: null,
    criticality: "required",
    requiresPhoto: false,
    requiresComment: false,
    localKey: makeLocalKey(),
  };
}

export function TemplateEditScreen({
  templateId,
  onBack,
  onSaved,
}: TemplateEditScreenProps): React.JSX.Element {
  const tTpl = useTranslations("templates");
  const tErr = useTranslations("errors");

  const [name, setName] = React.useState("");
  const [roleTarget, setRoleTarget] = React.useState<UserRole>("operator");
  const [tasks, setTasks] = React.useState<DraftTask[]>([emptyTask()]);
  const [loading, setLoading] = React.useState<boolean>(templateId !== null);
  const [saving, setSaving] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);

  // Bulk-import sheet state. Only shown when creating a brand-new template;
  // editing an existing template uses the per-task editor below.
  const [importOpen, setImportOpen] = React.useState(false);
  const [importContent, setImportContent] = React.useState("");
  const [importBusy, setImportBusy] = React.useState<"idle" | "preview" | "apply">("idle");
  const [importPreview, setImportPreview] = React.useState<ImportPreview | null>(null);
  const [importError, setImportError] = React.useState<string | null>(null);

  // Recurrence (auto-create daily shift) state.
  const [recurrence, setRecurrence] = React.useState<RecurrenceConfig | null>(null);
  const [locations, setLocations] = React.useState<LocationRow[]>([]);
  const [members, setMembers] = React.useState<TeamMemberRow[]>([]);

  // PointerSensor with a small activation distance so a finger tap in
  // a text field doesn't accidentally start a drag. KeyboardSensor lets
  // a screen-reader / keyboard user reorder using Space + Arrow keys
  // on the focused drag handle.
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  React.useEffect(() => {
    if (templateId === null) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    void (async () => {
      setLoading(true);
      const result = await getTemplate(templateId);
      if (cancelled) return;
      if (result.ok) {
        setName(result.data.name);
        setRoleTarget(result.data.roleTarget);
        setTasks(
          result.data.tasks.map((t) => ({
            id: t.id,
            title: t.title,
            description: t.description,
            section: t.section,
            criticality: t.criticality,
            requiresPhoto: t.requiresPhoto,
            requiresComment: t.requiresComment,
            localKey: t.id,
          })),
        );
        setRecurrence(result.data.recurrence);
      } else {
        toast({ variant: "critical", title: tErr("generic"), description: result.message });
      }
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [templateId, tErr]);

  // Locations + members are needed only by the recurrence block but the
  // requests are cheap (org-scoped, ≤ a few hundred rows). Fetch once on
  // mount; each subsequent open reuses the in-memory list.
  React.useEffect(() => {
    let cancelled = false;
    void (async () => {
      const [locResult, memResult] = await Promise.all([
        fetchLocations(),
        fetchTeamMembers(false),
      ]);
      if (cancelled) return;
      if (locResult.ok) setLocations(locResult.data);
      if (memResult.ok) setMembers(memResult.data.filter((m) => m.is_active));
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const updateTask = React.useCallback(
    (key: string, patch: Partial<DraftTask>) => {
      setTasks((prev) => prev.map((t) => (t.localKey === key ? { ...t, ...patch } : t)));
    },
    [],
  );

  const moveTask = React.useCallback(
    (key: string, direction: -1 | 1) => {
      setTasks((prev) => {
        const idx = prev.findIndex((t) => t.localKey === key);
        if (idx < 0) return prev;
        const target = idx + direction;
        if (target < 0 || target >= prev.length) return prev;
        return arrayMove(prev, idx, target);
      });
      haptic("light");
    },
    [],
  );

  const handleDragEnd = React.useCallback((event: DragEndEvent) => {
    const { active, over } = event;
    if (over === null || active.id === over.id) return;
    setTasks((prev) => {
      const oldIndex = prev.findIndex((t) => t.localKey === active.id);
      const newIndex = prev.findIndex((t) => t.localKey === over.id);
      if (oldIndex < 0 || newIndex < 0) return prev;
      return arrayMove(prev, oldIndex, newIndex);
    });
    haptic("medium");
  }, []);

  const addTask = React.useCallback(() => {
    setTasks((prev) => [...prev, emptyTask()]);
  }, []);

  const removeTask = React.useCallback((key: string) => {
    setTasks((prev) => (prev.length <= 1 ? prev : prev.filter((t) => t.localKey !== key)));
  }, []);

  // Client-side mirror of the server's `_validate`. We compute on every
  // render so the Save button can be disabled, but the work is O(n) on a
  // tiny list — well under a millisecond.
  const validation = React.useMemo<string | null>(() => {
    const trimmedName = name.trim();
    if (trimmedName.length < 3 || trimmedName.length > 128) {
      return tTpl("validation.nameLength");
    }
    if (tasks.length === 0) return tTpl("validation.minTasks");
    for (const t of tasks) {
      const title = t.title.trim();
      if (title.length < 3 || title.length > 255) {
        return tTpl("validation.taskTitle");
      }
    }
    return null;
  }, [name, tasks, tTpl]);

  const handleSave = React.useCallback(async () => {
    if (validation !== null) {
      toast({ variant: "warning", title: validation });
      return;
    }
    setSaving(true);
    const payload = {
      name: name.trim(),
      roleTarget,
      tasks: tasks.map<TemplateTaskInput>((t) => ({
        id: t.id,
        title: t.title.trim(),
        description: t.description?.trim() ? t.description.trim() : null,
        section: t.section?.trim() ? t.section.trim() : null,
        criticality: t.criticality,
        requiresPhoto: t.requiresPhoto,
        requiresComment: t.requiresComment,
      })),
      recurrence,
    };
    const result =
      templateId === null
        ? await createTemplate(payload)
        : await updateTemplate(templateId, payload);
    setSaving(false);
    if (!result.ok) {
      toast({
        variant: "critical",
        title: tTpl("saveError"),
        description: result.message,
      });
      notify("error");
      return;
    }
    notify("success");
    toast({ variant: "success", title: tTpl("saved") });
    onSaved();
  }, [name, roleTarget, tasks, recurrence, templateId, validation, tTpl, onSaved]);

  const handleImportPreview = React.useCallback(async () => {
    setImportError(null);
    if (importContent.trim().length === 0) {
      setImportError(tTpl("import.empty"));
      return;
    }
    if (name.trim().length < 3) {
      setImportError(tTpl("validation.nameLength"));
      return;
    }
    setImportBusy("preview");
    const result = await importTemplateDryRun({
      name: name.trim(),
      roleTarget,
      content: importContent,
    });
    setImportBusy("idle");
    if (!result.ok) {
      setImportError(
        result.code === "no_tasks_found" ? tTpl("import.noTasks") : result.message,
      );
      setImportPreview(null);
      return;
    }
    setImportPreview(result.data);
  }, [importContent, name, roleTarget, tTpl]);

  const handleImportApply = React.useCallback(async () => {
    setImportError(null);
    if (importContent.trim().length === 0 || importPreview === null) {
      setImportError(tTpl("import.previewFirst"));
      return;
    }
    if (name.trim().length < 3) {
      setImportError(tTpl("validation.nameLength"));
      return;
    }
    setImportBusy("apply");
    const result = await importTemplateApply({
      name: name.trim(),
      roleTarget,
      content: importContent,
    });
    setImportBusy("idle");
    if (!result.ok) {
      setImportError(
        result.code === "no_tasks_found" ? tTpl("import.noTasks") : result.message,
      );
      return;
    }
    notify("success");
    toast({
      variant: "success",
      title: tTpl("saved"),
      description: tTpl("import.applied", { count: result.data.taskCount }),
    });
    setImportOpen(false);
    setImportContent("");
    setImportPreview(null);
    onSaved();
  }, [importContent, importPreview, name, roleTarget, tTpl, onSaved]);

  const handleDelete = React.useCallback(async () => {
    if (templateId === null) return;
    if (!window.confirm(tTpl("confirmDelete"))) return;
    setDeleting(true);
    const result = await deleteTemplate(templateId);
    setDeleting(false);
    if (!result.ok) {
      toast({
        variant: "critical",
        title:
          result.code === "template_in_use"
            ? tTpl("deleteErrorInUse")
            : tErr("generic"),
        description: result.code === "template_in_use" ? undefined : result.message,
      });
      notify("error");
      return;
    }
    notify("success");
    toast({ variant: "success", title: tTpl("deleted") });
    onSaved();
  }, [templateId, tTpl, tErr, onSaved]);

  if (loading) {
    return (
      <main className="mx-auto max-w-md px-4 pt-4 pb-24 animate-fade-in-up">
        <Card className="animate-pulse">
          <CardContent className="p-6 h-40" />
        </Card>
      </main>
    );
  }

  const isEdit = templateId !== null;
  const taskIds = tasks.map((t) => t.localKey);

  return (
    <main className="mx-auto max-w-md px-4 pt-4 pb-24 animate-fade-in-up">
      <header className="flex items-center gap-3 mb-4">
        <Button variant="ghost" size="sm" onClick={onBack} className="-ml-2 px-2">
          <ArrowLeft className="size-5" />
        </Button>
        <h1 className="text-lg font-semibold flex-1">
          {isEdit ? tTpl("editTitle") : tTpl("createTitle")}
        </h1>
        {!isEdit ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setImportOpen(true)}
            aria-label={tTpl("import.openCta")}
          >
            <ClipboardPaste className="size-4" />
            {tTpl("import.openCta")}
          </Button>
        ) : null}
      </header>

      <Card className="mb-4">
        <CardContent className="p-4 space-y-3">
          <label className="block">
            <span className="text-xs font-medium text-muted-foreground">
              {tTpl("nameLabel")}
            </span>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={128}
              className="mt-1 w-full rounded-md bg-elevated p-2 text-sm border border-border focus:outline-none focus:ring-2 focus:ring-ring"
              placeholder={tTpl("namePlaceholder")}
            />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-muted-foreground">
              {tTpl("roleLabel")}
            </span>
            <select
              value={roleTarget}
              onChange={(e) => setRoleTarget(e.target.value as UserRole)}
              className="mt-1 w-full rounded-md bg-elevated p-2 text-sm border border-border focus:outline-none focus:ring-2 focus:ring-ring"
            >
              {ROLE_TARGETS.map((role) => (
                <option key={role} value={role}>
                  {tTpl(`role.${role}`)}
                </option>
              ))}
            </select>
          </label>
        </CardContent>
      </Card>

      <RecurrenceBlock
        value={recurrence}
        onChange={setRecurrence}
        locations={locations}
        members={members}
        roleTarget={roleTarget}
        tTpl={tTpl}
      />

      <div className="flex items-center justify-between mb-2">
        <h2 className="text-sm font-medium text-muted-foreground">
          {tTpl("tasksHeading", { count: tasks.length })}
        </h2>
        <Button variant="ghost" size="sm" onClick={addTask}>
          <Plus className="size-4" />
          {tTpl("addTaskCta")}
        </Button>
      </div>

      <p className="text-[11px] text-muted-foreground mb-2 px-1">{tTpl("reorderHint")}</p>

      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleDragEnd}
      >
        <SortableContext items={taskIds} strategy={verticalListSortingStrategy}>
          <ul className="space-y-2 mb-6">
            {tasks.map((task, index) => (
              <SortableTaskRow
                key={task.localKey}
                task={task}
                index={index}
                isFirst={index === 0}
                isLast={index === tasks.length - 1}
                canRemove={tasks.length > 1}
                criticalities={CRITICALITIES}
                tTpl={tTpl}
                onChange={updateTask}
                onMove={moveTask}
                onRemove={removeTask}
              />
            ))}
          </ul>
        </SortableContext>
      </DndContext>

      {validation ? (
        <div className="rounded-md border border-warning/40 bg-warning/10 p-3 mb-3 text-xs flex items-start gap-2">
          <AlertTriangle className="size-4 text-warning mt-0.5 shrink-0" />
          <span className="text-warning">{validation}</span>
        </div>
      ) : null}

      <Button size="block" onClick={handleSave} disabled={saving || validation !== null}>
        <Save className="size-4" />
        {saving ? tTpl("saving") : tTpl("saveCta")}
      </Button>

      {isEdit ? (
        <Button
          variant="ghost"
          size="block"
          onClick={handleDelete}
          disabled={deleting}
          className="mt-2 text-critical"
        >
          <Trash2 className="size-4" />
          {deleting ? tTpl("deleting") : tTpl("deleteCta")}
        </Button>
      ) : null}

      <Sheet open={importOpen} onOpenChange={setImportOpen}>
        <SheetContent title={tTpl("import.sheetTitle")} className="max-h-[90vh] overflow-y-auto">
          <p className="text-xs text-muted-foreground mb-3">{tTpl("import.help")}</p>

          <textarea
            value={importContent}
            onChange={(e) => {
              setImportContent(e.target.value);
              setImportPreview(null);
            }}
            placeholder={tTpl("import.placeholder")}
            rows={10}
            className="w-full rounded-md bg-elevated p-2 text-xs font-mono border border-border focus:outline-none focus:ring-2 focus:ring-ring"
            spellCheck={false}
          />

          {importError ? (
            <div className="mt-2 rounded-md border border-critical/40 bg-critical/10 p-2 text-xs text-critical">
              {importError}
            </div>
          ) : null}

          <div className="mt-3 flex gap-2">
            <Button
              variant="secondary"
              size="block"
              onClick={handleImportPreview}
              disabled={importBusy !== "idle"}
            >
              {importBusy === "preview" ? tTpl("import.previewing") : tTpl("import.previewCta")}
            </Button>
            <Button
              size="block"
              onClick={handleImportApply}
              disabled={importBusy !== "idle" || importPreview === null}
            >
              {importBusy === "apply" ? tTpl("import.applying") : tTpl("import.applyCta")}
            </Button>
          </div>

          {importPreview ? (
            <div className="mt-4 space-y-2">
              <p className="text-xs font-medium text-muted-foreground">
                {tTpl("import.previewSummary", {
                  sections: importPreview.sections.length,
                  tasks: importPreview.tasks.length,
                })}
              </p>
              <ul className="rounded-md border border-border bg-elevated text-xs divide-y divide-border max-h-64 overflow-y-auto">
                {importPreview.tasks.map((t, idx) => (
                  <li key={idx} className="p-2">
                    {t.section ? (
                      <span className="text-[10px] uppercase tracking-wide text-muted-foreground mr-2">
                        {t.section}
                      </span>
                    ) : null}
                    <span>{t.title}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </SheetContent>
      </Sheet>
    </main>
  );
}

/**
 * One row in the sortable list. Pulled into its own component because
 * `useSortable` is a hook and can't live inside a `.map` callback —
 * conditional hook usage rules forbid it. As a side benefit, React
 * memoises rerenders to just the row whose state changed.
 */
type Translator = ReturnType<typeof useTranslations>;

interface SortableTaskRowProps {
  task: DraftTask;
  index: number;
  isFirst: boolean;
  isLast: boolean;
  canRemove: boolean;
  criticalities: ReadonlyArray<Criticality>;
  tTpl: Translator;
  onChange: (key: string, patch: Partial<DraftTask>) => void;
  onMove: (key: string, direction: -1 | 1) => void;
  onRemove: (key: string) => void;
}

function SortableTaskRow({
  task,
  index,
  isFirst,
  isLast,
  canRemove,
  criticalities,
  tTpl,
  onChange,
  onMove,
  onRemove,
}: SortableTaskRowProps): React.JSX.Element {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: task.localKey });

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.6 : 1,
    zIndex: isDragging ? 10 : "auto",
  };

  return (
    <li ref={setNodeRef} style={style}>
      <Card accent={task.criticality === "critical" ? "critical" : "none"}>
        <CardContent className="p-3 space-y-2">
          <div className="flex items-start gap-2">
            <button
              type="button"
              className="touch-none cursor-grab active:cursor-grabbing rounded p-1 text-muted-foreground hover:bg-elevated focus:outline-none focus:ring-2 focus:ring-ring"
              aria-label={tTpl("dragHandleAria")}
              {...attributes}
              {...listeners}
            >
              <GripVertical className="size-4" />
            </button>
            <span className="text-[11px] font-mono text-muted-foreground pt-2 w-5 text-right">
              {index + 1}
            </span>
            <input
              type="text"
              value={task.title}
              onChange={(e) => onChange(task.localKey, { title: e.target.value })}
              maxLength={255}
              className="flex-1 rounded-md bg-elevated p-2 text-sm border border-border focus:outline-none focus:ring-2 focus:ring-ring"
              placeholder={tTpl("taskTitlePlaceholder")}
            />
          </div>

          <input
            type="text"
            value={task.section ?? ""}
            onChange={(e) =>
              onChange(task.localKey, {
                section: e.target.value === "" ? null : e.target.value,
              })
            }
            maxLength={64}
            className="w-full rounded-md bg-elevated p-2 text-xs border border-border focus:outline-none focus:ring-2 focus:ring-ring"
            placeholder={tTpl("taskSectionPlaceholder")}
            aria-label={tTpl("taskSectionLabel")}
          />

          <textarea
            value={task.description ?? ""}
            onChange={(e) =>
              onChange(task.localKey, {
                description: e.target.value === "" ? null : e.target.value,
              })
            }
            maxLength={2000}
            className="w-full min-h-[44px] rounded-md bg-elevated p-2 text-sm border border-border focus:outline-none focus:ring-2 focus:ring-ring"
            placeholder={tTpl("taskDescriptionPlaceholder")}
            rows={2}
          />

          <div className="flex flex-wrap items-center gap-2">
            <select
              value={task.criticality}
              onChange={(e) =>
                onChange(task.localKey, {
                  criticality: e.target.value as Criticality,
                })
              }
              className="rounded-md bg-elevated px-2 py-1 text-xs border border-border focus:outline-none focus:ring-2 focus:ring-ring"
              aria-label={tTpl("criticalityLabel")}
            >
              {criticalities.map((c) => (
                <option key={c} value={c}>
                  {tTpl(`criticality.${c}`)}
                </option>
              ))}
            </select>

            <Toggle
              icon={<Camera className="size-3.5" />}
              label={tTpl("photoFlag")}
              pressed={task.requiresPhoto}
              onChange={(v) => onChange(task.localKey, { requiresPhoto: v })}
            />
            <Toggle
              icon={<MessageSquare className="size-3.5" />}
              label={tTpl("commentFlag")}
              pressed={task.requiresComment}
              onChange={(v) => onChange(task.localKey, { requiresComment: v })}
            />
          </div>

          <div className="flex items-center justify-end gap-1 pt-1 border-t border-border/40">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onMove(task.localKey, -1)}
              disabled={isFirst}
              aria-label={tTpl("moveUpAria")}
            >
              <ArrowUp className="size-4" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onMove(task.localKey, 1)}
              disabled={isLast}
              aria-label={tTpl("moveDownAria")}
            >
              <ArrowDown className="size-4" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onRemove(task.localKey)}
              disabled={!canRemove}
              aria-label={tTpl("removeAria")}
              className="text-critical"
            >
              <Trash2 className="size-4" />
            </Button>
          </div>
        </CardContent>
      </Card>
    </li>
  );
}

/**
 * Tiny pill-style toggle. We avoid pulling in a switch component because
 * we only need three of them and the visual language stays clearer when
 * everything is rendered with the same `Card`/`Button` primitives.
 */
function Toggle({
  icon,
  label,
  pressed,
  onChange,
}: {
  icon: React.ReactNode;
  label: string;
  pressed: boolean;
  onChange: (v: boolean) => void;
}): React.JSX.Element {
  return (
    <button
      type="button"
      onClick={() => onChange(!pressed)}
      aria-pressed={pressed}
      className={[
        "flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs border transition-colors",
        pressed
          ? "bg-primary/10 border-primary/40 text-primary"
          : "bg-elevated border-border text-muted-foreground",
      ].join(" ")}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}

const ALL_WEEKDAYS: ReadonlyArray<number> = [1, 2, 3, 4, 5, 6, 7];

/**
 * Editor for `Template.default_schedule`.
 *
 * Why a single block (instead of a separate page)
 * -----------------------------------------------
 * Recurrence and the task list are *one* contract from the owner's POV
 * — "the kitchen morning checklist runs every day at 09:00 in the
 * downtown bar". Splitting them across screens means the owner has to
 * remember to set both, and we lose the single-save discoverability.
 *
 * Default values (when the toggle is first turned on) are picked to be
 * obviously editable, not "smart": 09:00, 480-min duration, all
 * weekdays, the first available location. Smart defaults invite
 * surprises; explicit defaults invite review.
 */
function RecurrenceBlock({
  value,
  onChange,
  locations,
  members,
  roleTarget,
  tTpl,
}: {
  value: RecurrenceConfig | null;
  onChange: (next: RecurrenceConfig | null) => void;
  locations: LocationRow[];
  members: TeamMemberRow[];
  roleTarget: UserRole;
  tTpl: Translator;
}): React.JSX.Element {
  const enabled = value !== null && value.autoCreate;

  const enable = React.useCallback(() => {
    if (value && value.autoCreate) return;
    if (locations.length === 0) {
      toast({ variant: "warning", title: tTpl("recurrence.noLocations") });
      return;
    }
    const fallback: RecurrenceConfig = value ?? {
      kind: "daily",
      autoCreate: true,
      timeOfDay: "09:00",
      durationMin: 480,
      weekdays: [1, 2, 3, 4, 5, 6, 7],
      timezone: locations[0]?.timezone ?? "UTC",
      locationId: locations[0]?.id ?? "",
      defaultAssigneeId: null,
      leadTimeMin: 0,
    };
    onChange({ ...fallback, autoCreate: true });
  }, [value, locations, onChange, tTpl]);

  const disable = React.useCallback(() => {
    if (value === null) return;
    onChange({ ...value, autoCreate: false });
  }, [value, onChange]);

  const update = React.useCallback(
    (patch: Partial<RecurrenceConfig>) => {
      if (value === null) return;
      onChange({ ...value, ...patch });
    },
    [value, onChange],
  );

  return (
    <Card className="mb-4">
      <CardContent className="p-4 space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-sm font-medium">{tTpl("recurrence.title")}</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              {tTpl("recurrence.subtitle")}
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={enabled}
            onClick={enabled ? disable : enable}
            className={[
              "relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors",
              enabled ? "bg-primary" : "bg-elevated border border-border",
            ].join(" ")}
          >
            <span
              className={[
                "inline-block h-4 w-4 transform rounded-full bg-white transition-transform",
                enabled ? "translate-x-6" : "translate-x-1",
              ].join(" ")}
            />
          </button>
        </div>

        {enabled && value !== null ? (
          <div className="space-y-3 pt-2 border-t border-border">
            <div className="grid grid-cols-2 gap-2">
              <label className="block">
                <span className="text-xs text-muted-foreground">
                  {tTpl("recurrence.timeLabel")}
                </span>
                <input
                  type="time"
                  value={value.timeOfDay}
                  onChange={(e) => update({ timeOfDay: e.target.value })}
                  className="mt-1 w-full rounded-md bg-elevated p-2 text-sm border border-border focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </label>
              <label className="block">
                <span className="text-xs text-muted-foreground">
                  {tTpl("recurrence.durationLabel")}
                </span>
                <input
                  type="number"
                  value={value.durationMin}
                  min={15}
                  max={24 * 60}
                  step={15}
                  onChange={(e) => update({ durationMin: Number(e.target.value) || 480 })}
                  className="mt-1 w-full rounded-md bg-elevated p-2 text-sm border border-border focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </label>
            </div>

            <div>
              <span className="text-xs text-muted-foreground">
                {tTpl("recurrence.weekdaysLabel")}
              </span>
              <div className="mt-1 flex gap-1 flex-wrap">
                {ALL_WEEKDAYS.map((d) => {
                  const active = value.weekdays.includes(d);
                  return (
                    <button
                      key={d}
                      type="button"
                      onClick={() => {
                        const next = active
                          ? value.weekdays.filter((x) => x !== d)
                          : [...value.weekdays, d].sort((a, b) => a - b);
                        update({ weekdays: next.length === 0 ? [d] : next });
                      }}
                      aria-pressed={active}
                      className={[
                        "px-2.5 py-1 rounded-full text-xs border transition-colors",
                        active
                          ? "bg-primary/10 border-primary/40 text-primary"
                          : "bg-elevated border-border text-muted-foreground",
                      ].join(" ")}
                    >
                      {tTpl(`recurrence.weekday.${d}`)}
                    </button>
                  );
                })}
              </div>
            </div>

            <label className="block">
              <span className="text-xs text-muted-foreground">
                {tTpl("recurrence.locationLabel")}
              </span>
              <select
                value={value.locationId}
                onChange={(e) => {
                  const loc = locations.find((l) => l.id === e.target.value);
                  update({
                    locationId: e.target.value,
                    timezone: loc?.timezone ?? value.timezone,
                  });
                }}
                className="mt-1 w-full rounded-md bg-elevated p-2 text-sm border border-border focus:outline-none focus:ring-2 focus:ring-ring"
              >
                {locations.map((loc) => (
                  <option key={loc.id} value={loc.id}>
                    {loc.name} · {loc.timezone}
                  </option>
                ))}
              </select>
            </label>

            <label className="block">
              <span className="text-xs text-muted-foreground">
                {tTpl("recurrence.assigneeLabel")}
              </span>
              <select
                value={value.defaultAssigneeId ?? ""}
                onChange={(e) =>
                  update({ defaultAssigneeId: e.target.value === "" ? null : e.target.value })
                }
                className="mt-1 w-full rounded-md bg-elevated p-2 text-sm border border-border focus:outline-none focus:ring-2 focus:ring-ring"
              >
                <option value="">{tTpl("recurrence.assigneeAuto")}</option>
                {members
                  .filter((m) => memberAssignableForRoleTarget(roleTarget, m.role))
                  .map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.full_name} · {m.role}
                    </option>
                  ))}
              </select>
            </label>

            <label className="block">
              <span className="text-xs text-muted-foreground">
                {tTpl("recurrence.leadTimeLabel")}
              </span>
              <input
                type="number"
                value={value.leadTimeMin}
                min={0}
                max={12 * 60}
                step={15}
                onChange={(e) => update({ leadTimeMin: Number(e.target.value) || 0 })}
                className="mt-1 w-full rounded-md bg-elevated p-2 text-sm border border-border focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </label>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
