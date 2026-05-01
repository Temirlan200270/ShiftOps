/** Single-tenant display timezone (no org picker yet). */

export const APP_TIMEZONE =
  typeof process.env.NEXT_PUBLIC_APP_TIMEZONE === "string" &&
  process.env.NEXT_PUBLIC_APP_TIMEZONE.length > 0
    ? process.env.NEXT_PUBLIC_APP_TIMEZONE
    : "Asia/Almaty";

function ymdInTimeZone(d: Date, timeZone: string): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(d);
  const y = parts.find((p) => p.type === "year")?.value ?? "1970";
  const m = parts.find((p) => p.type === "month")?.value ?? "01";
  const day = parts.find((p) => p.type === "day")?.value ?? "01";
  return `${y}-${m}-${day}`;
}

function daysFromEventToToday(eventYmd: string, todayYmd: string): number {
  const ep = eventYmd.split("-").map((x) => Number.parseInt(x, 10));
  const tp = todayYmd.split("-").map((x) => Number.parseInt(x, 10));
  const ey = ep[0] ?? 1970;
  const em = ep[1] ?? 1;
  const ed = ep[2] ?? 1;
  const ty = tp[0] ?? 1970;
  const tm = tp[1] ?? 1;
  const td = tp[2] ?? 1;
  const eUtc = Date.UTC(ey, em - 1, ed);
  const tUtc = Date.UTC(ty, tm - 1, td);
  return Math.round((tUtc - eUtc) / 86_400_000);
}

export interface AuditTimeLabels {
  today: (time: string) => string;
  yesterday: (time: string) => string;
}

/**
 * Formats audit ``created_at`` (ISO UTC) for the journal: today / yesterday /
 * short calendar date, no seconds — all in ``APP_TIMEZONE``.
 */
export function formatAuditTimestamp(
  isoUtc: string,
  locale: string,
  labels: AuditTimeLabels,
  timeZone: string = APP_TIMEZONE,
): string {
  const d = new Date(isoUtc);
  if (Number.isNaN(d.getTime())) return isoUtc;

  const now = new Date();
  const eventYmd = ymdInTimeZone(d, timeZone);
  const todayYmd = ymdInTimeZone(now, timeZone);
  const offsetDays = daysFromEventToToday(eventYmd, todayYmd);

  const hm = new Intl.DateTimeFormat(locale, {
    timeZone,
    hour: "2-digit",
    minute: "2-digit",
  }).format(d);

  if (offsetDays === 0) {
    return labels.today(hm);
  }
  if (offsetDays === 1) {
    return labels.yesterday(hm);
  }

  const eventYear = Number.parseInt(eventYmd.slice(0, 4), 10);
  const todayYear = Number.parseInt(todayYmd.slice(0, 4), 10);

  if (eventYear === todayYear) {
    return new Intl.DateTimeFormat(locale, {
      timeZone,
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(d);
  }

  return new Intl.DateTimeFormat(locale, {
    timeZone,
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(d);
}

export function actorInitials(actorName: string | null | undefined): string {
  const raw = actorName?.trim();
  if (!raw) return "?";
  const parts = raw.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) {
    const a = parts[0]?.[0];
    const b = parts[1]?.[0];
    if (a !== undefined && b !== undefined) {
      return `${a}${b}`.toUpperCase();
    }
  }
  const single = parts[0] ?? raw;
  if (single.length <= 2) return single.toUpperCase();
  return single.slice(0, 2).toUpperCase();
}
