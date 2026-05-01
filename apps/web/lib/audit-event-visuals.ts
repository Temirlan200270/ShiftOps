import type { LucideIcon } from "lucide-react";
import {
  AlertTriangle,
  CalendarClock,
  CheckCircle2,
  CircleCheck,
  Pencil,
  Play,
  ScrollText,
  ShieldCheck,
  ShieldX,
  Trash2,
  Upload,
  Users,
} from "lucide-react";

export type AuditAccent = "neutral" | "positive" | "warning" | "danger" | "info";

export function normalizeAuditAccent(raw: string): AuditAccent {
  if (raw === "positive" || raw === "warning" || raw === "danger" || raw === "info") {
    return raw;
  }
  return "neutral";
}

export function auditBorderClass(accent: AuditAccent): string {
  switch (accent) {
    case "positive":
      return "border-l-emerald-500";
    case "warning":
      return "border-l-amber-500";
    case "danger":
      return "border-l-destructive";
    case "info":
      return "border-l-sky-500";
    default:
      return "border-l-border";
  }
}

export function auditIconWrapClass(accent: AuditAccent): string {
  switch (accent) {
    case "positive":
      return "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400";
    case "warning":
      return "bg-amber-500/15 text-amber-600 dark:text-amber-400";
    case "danger":
      return "bg-destructive/15 text-destructive";
    case "info":
      return "bg-sky-500/15 text-sky-600 dark:text-sky-400";
    default:
      return "bg-muted text-muted-foreground";
  }
}

export function auditEventIcon(eventType: string, accent: AuditAccent): LucideIcon {
  if (eventType === "shift.started") {
    return Play;
  }
  if (eventType === "shift.closed") {
    return accent === "warning" ? AlertTriangle : CheckCircle2;
  }
  if (eventType === "template.created" || eventType === "template.updated") {
    return Pencil;
  }
  if (eventType === "template.deleted") {
    return Trash2;
  }
  if (eventType === "schedule.imported") {
    return Upload;
  }
  if (eventType === "waiver.requested") {
    return AlertTriangle;
  }
  if (eventType === "waiver.approve") {
    return ShieldCheck;
  }
  if (eventType === "waiver.reject") {
    return ShieldX;
  }
  if (eventType === "task.completed") {
    return accent === "warning" ? AlertTriangle : CircleCheck;
  }
  if (eventType === "member.updated") {
    return Users;
  }
  if (eventType.includes("schedule") || eventType.includes("import")) {
    return CalendarClock;
  }
  return ScrollText;
}
