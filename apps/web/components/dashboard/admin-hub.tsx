"use client";

import {
  BarChart3,
  CalendarDays,
  FileStack,
  History,
  Radio,
  ScrollText,
  Upload,
  Users,
  type LucideIcon,
} from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { GlassMenu, GlassMenuRow } from "@/components/dashboard/glass-menu";
import { cn } from "@/lib/utils";

export type AdminHubNavTarget =
  | "analytics"
  | "team"
  | "liveMonitor"
  | "templatesList"
  | "audit"
  | "businessHours"
  | "csvImport"
  | "history";

export interface AdminHubProps {
  hubLoading: boolean;
  activeShiftsCount: number | null;
  averageScore: number | null;
  liveUnavailable: boolean;
  kpiUnavailable: boolean;
  onNavigate: (target: AdminHubNavTarget) => void;
  onOpenTemplates: () => void;
}

function HubTile({
  icon: Icon,
  title,
  subtitle,
  onClick,
}: {
  icon: LucideIcon;
  title: string;
  subtitle: string;
  onClick: () => void;
}): React.JSX.Element {
  return (
    <button
      type="button"
      className={cn(
        "touch-target so-card-solid so-press flex min-h-[92px] flex-col justify-between rounded-2xl p-4 text-left",
      )}
      onClick={onClick}
    >
      <div className="flex items-start justify-between gap-1">
        <span className="text-[15px] font-semibold leading-tight text-foreground">{title}</span>
        <Icon className="h-5 w-5 shrink-0 text-primary" aria-hidden />
      </div>
      <p className="mt-2 text-[11px] leading-snug text-muted-foreground">{subtitle}</p>
    </button>
  );
}

export function AdminHub({
  hubLoading,
  activeShiftsCount,
  averageScore,
  liveUnavailable,
  kpiUnavailable,
  onNavigate,
  onOpenTemplates,
}: AdminHubProps): React.JSX.Element {
  const t = useTranslations("dashboard.hub");

  const scoreDisplay =
    kpiUnavailable || averageScore === null ? "—" : String(Math.round(averageScore * 10) / 10);

  const liveLine = hubLoading
    ? "…"
    : liveUnavailable || activeShiftsCount === null
      ? t("liveStrip.countUnavailable")
      : t("liveStrip.headline", { count: activeShiftsCount });

  return (
    <section className="mb-8 border-b border-white/[0.06] pb-6">
      <p className="mb-1 text-xs text-muted-foreground">{t("orgEyebrow")}</p>
      <h2 className="mb-4 text-xl font-bold tracking-tight text-foreground">{t("panelTitle")}</h2>
      <p className="mb-5 text-xs text-muted-foreground">{t("panelIntro")}</p>

      <div className="so-card-solid mb-6 flex flex-wrap items-center justify-between gap-4 rounded-2xl p-4">
        {hubLoading ? (
          <div className="h-14 w-full animate-pulse rounded-lg bg-muted/40" />
        ) : (
          <>
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-[11px] font-extrabold uppercase tracking-wider text-success">
                <span className="so-pulse-dot shrink-0" />
                <span>{t("liveStrip.badge")}</span>
              </div>
              <p className="mt-1 text-[15px] font-semibold leading-snug text-foreground">{liveLine}</p>
            </div>
            <div className="text-right">
              <p className="text-[10px] font-extrabold uppercase tracking-wider text-muted-foreground">
                {t("liveStrip.kpiLabel")}
              </p>
              <p
                className={cn(
                  "text-2xl font-bold tabular-nums-so",
                  !kpiUnavailable && averageScore !== null ? "text-warning" : "text-muted-foreground",
                )}
              >
                {scoreDisplay}
              </p>
            </div>
          </>
        )}
      </div>

      <p className="so-sec-title">{t("primarySection")}</p>
      <div className="grid grid-cols-2 gap-2">
        <HubTile
          icon={BarChart3}
          title={t("tiles.analytics.title")}
          subtitle={t("tiles.analytics.subtitle")}
          onClick={() => onNavigate("analytics")}
        />
        <HubTile
          icon={Users}
          title={t("tiles.team.title")}
          subtitle={t("tiles.team.subtitle")}
          onClick={() => onNavigate("team")}
        />
        <HubTile
          icon={Radio}
          title={t("tiles.live.title")}
          subtitle={t("tiles.live.subtitle")}
          onClick={() => onNavigate("liveMonitor")}
        />
        <HubTile
          icon={FileStack}
          title={t("tiles.templates.title")}
          subtitle={t("tiles.templates.subtitle")}
          onClick={onOpenTemplates}
        />
      </div>

      <p className="so-sec-title">{t("moreSection")}</p>
      <GlassMenu>
        <GlassMenuRow
          icon={ScrollText}
          title={t("more.audit.title")}
          subtitle={t("more.audit.subtitle")}
          onClick={() => onNavigate("audit")}
        />
        <GlassMenuRow
          icon={CalendarDays}
          title={t("more.hours.title")}
          subtitle={t("more.hours.subtitle")}
          onClick={() => onNavigate("businessHours")}
        />
        <GlassMenuRow
          icon={Upload}
          title={t("more.csv.title")}
          subtitle={t("more.csv.subtitle")}
          onClick={() => onNavigate("csvImport")}
        />
        <GlassMenuRow
          icon={History}
          title={t("more.history.title")}
          subtitle={t("more.history.subtitle")}
          onClick={() => onNavigate("history")}
        />
      </GlassMenu>
    </section>
  );
}
