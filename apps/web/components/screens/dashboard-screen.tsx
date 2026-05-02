"use client";

import {
  ArrowLeftRight,
  Clock3,
  History,
  PlayCircle,
  Settings,
  Sparkles,
} from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { AdminHub, type AdminHubNavTarget } from "@/components/dashboard/admin-hub";
import { GlassMenu, GlassMenuRow } from "@/components/dashboard/glass-menu";
import { AnalyticsScreen } from "@/components/screens/analytics-screen";
import { AuditScreen } from "@/components/screens/audit-screen";
import { BusinessHoursScreen } from "@/components/screens/business-hours-screen";
import { CsvImportScreen } from "@/components/screens/csv-import-screen";
import { HistoryScreen, type HistoryFilters } from "@/components/screens/history-screen";
import { LiveMonitorScreen } from "@/components/screens/live-monitor-screen";
import { SettingsScreen } from "@/components/screens/settings-screen";
import { SwapRequestsScreen } from "@/components/screens/swap-requests-screen";
import { TaskListScreen } from "@/components/screens/task-list-screen";
import { SummaryScreen } from "@/components/screens/summary-screen";
import { TeamScreen } from "@/components/screens/team-screen";
import { TemplateEditScreen } from "@/components/screens/template-edit-screen";
import { TemplatesListScreen } from "@/components/screens/templates-list-screen";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { fetchOverview } from "@/lib/api/analytics";
import { fetchMonitorSnapshot } from "@/lib/api/monitor";
import {
  claimShift,
  fetchAvailableShifts,
  fetchMyShift,
  readClientGeoForShiftStart,
  startShift,
  type VacantShift,
} from "@/lib/api/shifts";
import { useCapabilities } from "@/lib/hooks/use-capabilities";
import { localiseApiFailure } from "@/lib/i18n/api-errors";
import { useShiftStore } from "@/lib/stores/shift-store";
import { toast } from "@/lib/stores/toast-store";
import { cn } from "@/lib/utils";
import { haptic, notify } from "@/lib/telegram/init";
import { useTelegramShiftChrome } from "@/lib/telegram/shift-chrome";

type View =
  | "dashboard"
  | "tasks"
  | "summary"
  | "history"
  | "templatesList"
  | "templateEdit"
  | "audit"
  | "analytics"
  | "csvImport"
  | "businessHours"
  | "liveMonitor"
  | "swapRequests"
  | "team"
  | "settings";

const ADMIN_ONLY_VIEWS: View[] = [
  "audit",
  "analytics",
  "businessHours",
  "csvImport",
  "liveMonitor",
  "team",
  "templatesList",
  "templateEdit",
];

const primaryCtaClass =
  "!bg-white !text-black rounded-2xl border-0 font-bold shadow-[0_4px_28px_rgba(0,0,0,0.45)] hover:!bg-white/90 hover:!text-black";

export function DashboardScreen(): React.JSX.Element {
  const shift = useShiftStore((s) => s.shift);
  const setShift = useShiftStore((s) => s.setShift);
  const [view, setView] = React.useState<View>("dashboard");
  const [loading, setLoading] = React.useState(true);
  const [acting, setActing] = React.useState(false);
  const [vacantShifts, setVacantShifts] = React.useState<VacantShift[]>([]);
  const [claimingId, setClaimingId] = React.useState<string | null>(null);
  const lastShiftToastAtRef = React.useRef(0);
  const tDash = useTranslations("dashboard");
  const tErr = useTranslations("errors");
  const tHist = useTranslations("history");
  const tSwap = useTranslations("swap");
  const tSettings = useTranslations("settings");
  const caps = useCapabilities();
  const [editingTemplateId, setEditingTemplateId] = React.useState<string | null>(null);
  const [historyFilters, setHistoryFilters] = React.useState<HistoryFilters | null>(null);
  const [swapDeepLinkProposerId, setSwapDeepLinkProposerId] = React.useState<string | null>(null);

  const [hubLoading, setHubLoading] = React.useState(true);
  const [hubActiveCount, setHubActiveCount] = React.useState<number | null>(null);
  const [hubScore, setHubScore] = React.useState<number | null>(null);
  const [hubLiveOk, setHubLiveOk] = React.useState(true);
  const [hubKpiOk, setHubKpiOk] = React.useState(true);

  React.useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const sp = params.get("swap_proposer_shift");
    if (sp && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(sp)) {
      setSwapDeepLinkProposerId(sp);
      setView("swapRequests");
      window.history.replaceState({}, "", window.location.pathname || "/");
    }
  }, []);

  React.useEffect(() => {
    if (!caps.canAccessAdminModules && ADMIN_ONLY_VIEWS.includes(view)) {
      setView("dashboard");
    }
  }, [caps.canAccessAdminModules, view]);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    const [myResult, availResult] = await Promise.all([
      fetchMyShift(),
      fetchAvailableShifts(),
    ]);
    if (availResult.ok) {
      setVacantShifts(availResult.data);
    } else {
      setVacantShifts([]);
    }
    if (myResult.ok) {
      setShift(myResult.data);
    } else {
      const now = Date.now();
      if (now - lastShiftToastAtRef.current >= 3800) {
        lastShiftToastAtRef.current = now;
        toast({
          variant: "critical",
          title: tErr("generic"),
          description: localiseApiFailure(myResult, tErr),
        });
      }
    }
    setLoading(false);
  }, [setShift, tErr]);

  React.useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  React.useEffect(() => {
    if (!caps.canAccessAdminModules) {
      setHubLoading(false);
      setHubActiveCount(null);
      setHubScore(null);
      setHubLiveOk(true);
      setHubKpiOk(true);
      return;
    }
    let cancelled = false;
    setHubLoading(true);
    void (async () => {
      const [mon, ov] = await Promise.all([fetchMonitorSnapshot(), fetchOverview({ days: 1 })]);
      if (cancelled) return;
      setHubLoading(false);
      if (mon.ok) {
        setHubActiveCount(mon.data.active.length);
        setHubLiveOk(true);
      } else {
        setHubActiveCount(null);
        setHubLiveOk(false);
      }
      if (ov.ok) {
        setHubScore(ov.data.kpis.averageScore);
        setHubKpiOk(true);
      } else {
        setHubScore(null);
        setHubKpiOk(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [caps.canAccessAdminModules]);

  const handleClaimVacant = React.useCallback(
    async (row: VacantShift) => {
      setClaimingId(row.id);
      haptic("medium");
      const geo = await readClientGeoForShiftStart();
      const result = await claimShift(row.id, geo);
      setClaimingId(null);
      if (result.ok && result.data) {
        setShift(result.data);
        setVacantShifts([]);
        notify("success");
        setView("tasks");
      } else if (!result.ok) {
        notify("error");
        if (result.code === "shift_taken") {
          await refresh();
          toast({
            variant: "critical",
            title: tErr("shiftTakenTitle"),
            description: tErr("shiftTaken"),
          });
        } else {
          toast({
            variant: "critical",
            title: tErr("generic"),
            description: localiseApiFailure(result, tErr),
          });
        }
      }
    },
    [refresh, setShift, tErr],
  );

  const handleStart = React.useCallback(async () => {
    if (!shift) return;
    setActing(true);
    haptic("medium");
    const geo = await readClientGeoForShiftStart();
    const result = await startShift(shift.id, geo);
    setActing(false);
    if (result.ok) {
      setShift(result.data);
      notify("success");
      setView("tasks");
    } else {
      notify("error");
      toast({
        variant: "critical",
        title: tErr("generic"),
        description: localiseApiFailure(result, tErr),
      });
    }
  }, [shift, setShift, tErr]);

  const handleAdminNavigate = React.useCallback((target: AdminHubNavTarget) => {
    haptic("light");
    if (target === "history") {
      setHistoryFilters(null);
    }
    setView(target);
  }, []);

  const chromeSurface =
    view === "tasks" ? "tasks" : view === "dashboard" ? "dashboard" : "other";
  useTelegramShiftChrome({ shift, surface: chromeSurface });

  if (view === "tasks" && shift) {
    return (
      <TaskListScreen
        onBack={() => setView("dashboard")}
        onClosed={() => {
          setView("summary");
          void refresh();
        }}
      />
    );
  }
  if (view === "summary" && shift) {
    return <SummaryScreen onBack={() => setView("dashboard")} />;
  }
  if (view === "history") {
    return (
      <HistoryScreen
        onBack={() => {
          setHistoryFilters(null);
          setView("dashboard");
        }}
        filters={historyFilters ?? undefined}
        onClearFilters={() => setHistoryFilters(null)}
      />
    );
  }
  if (view === "audit" && caps.canAccessAdminModules) {
    return <AuditScreen onBack={() => setView("dashboard")} />;
  }
  if (view === "templatesList" && caps.canAccessAdminModules) {
    return (
      <TemplatesListScreen
        onBack={() => setView("dashboard")}
        onOpen={(id) => {
          setEditingTemplateId(id);
          setView("templateEdit");
        }}
      />
    );
  }
  if (view === "templateEdit" && caps.canAccessAdminModules) {
    return (
      <TemplateEditScreen
        templateId={editingTemplateId}
        onBack={() => setView("templatesList")}
        onSaved={() => {
          setEditingTemplateId(null);
          setView("templatesList");
        }}
      />
    );
  }
  if (view === "analytics" && caps.canAccessAdminModules) {
    return (
      <AnalyticsScreen
        onBack={() => setView("dashboard")}
        onOpenInHistory={(filters) => {
          setHistoryFilters(filters);
          setView("history");
        }}
      />
    );
  }
  if (view === "csvImport" && caps.canAccessAdminModules) {
    return <CsvImportScreen onBack={() => setView("dashboard")} />;
  }
  if (view === "businessHours" && caps.canAccessAdminModules) {
    return <BusinessHoursScreen onBack={() => setView("dashboard")} />;
  }
  if (view === "liveMonitor" && caps.canAccessAdminModules) {
    return <LiveMonitorScreen onBack={() => setView("dashboard")} />;
  }
  if (view === "team" && caps.canAccessAdminModules) {
    return <TeamScreen onBack={() => setView("dashboard")} />;
  }
  if (view === "settings") {
    return <SettingsScreen onBack={() => setView("dashboard")} />;
  }
  if (view === "swapRequests") {
    return (
      <SwapRequestsScreen
        onBack={() => {
          setSwapDeepLinkProposerId(null);
          setView("dashboard");
        }}
        deepLinkProposerShiftId={swapDeepLinkProposerId}
        onConsumedDeepLink={() => setSwapDeepLinkProposerId(null)}
      />
    );
  }

  const tasks = shift?.tasks ?? [];
  const total = tasks.length;
  const done = tasks.filter((t) => t.status === "done" || t.status === "waived").length;
  const remaining = total - done;
  const criticalLeft = tasks.filter(
    (t) => t.criticality === "critical" && t.status === "pending",
  ).length;
  const progress = total === 0 ? 0 : Math.round((done / total) * 100);

  return (
    <main className="mx-auto max-w-md px-4 pt-6 pb-24 animate-fade-in-up">
      {caps.canAccessAdminModules ? (
        <AdminHub
          hubLoading={hubLoading}
          activeShiftsCount={hubActiveCount}
          averageScore={hubScore}
          liveUnavailable={!hubLiveOk}
          kpiUnavailable={!hubKpiOk}
          onNavigate={handleAdminNavigate}
          onOpenTemplates={() => {
            haptic("light");
            setEditingTemplateId(null);
            setView("templatesList");
          }}
        />
      ) : null}

      <section className="mb-4">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          {caps.canAccessAdminModules
            ? tDash("shiftSection.eyebrowAdmin")
            : tDash("shiftSection.eyebrow")}
        </p>
        <p className="text-sm text-muted-foreground">{new Date().toLocaleDateString()}</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-foreground">
          {shift?.templateName ?? "ShiftOps"}
        </h1>
        {shift ? (
          <div className="mt-2 space-y-0.5">
            {shift.stationLabel ? (
              <p className="text-sm text-muted-foreground">
                {tDash("stationLabel", { label: shift.stationLabel })} ·{" "}
                {tDash("slotIndexShort", { index: shift.slotIndex })}
              </p>
            ) : (
              <p className="text-sm text-muted-foreground">
                {tDash("slotIndexShort", { index: shift.slotIndex })}
              </p>
            )}
            <p className="text-sm text-muted-foreground">
              {tDash("operatorOnShift", { name: shift.operatorFullName })}
            </p>
          </div>
        ) : null}
      </section>

      {loading && !shift ? (
        <div className="so-glass mb-4 h-40 animate-pulse rounded-2xl" />
      ) : !shift ? (
        <>
          {vacantShifts.length > 0 ? (
            <div className="so-glass mb-3 rounded-2xl p-4">
              <p className="mb-3 font-medium text-foreground">{tDash("availableTitle")}</p>
              <div className="space-y-3">
                {vacantShifts.map((row) => (
                  <div
                    key={row.id}
                    className="flex flex-col gap-2 rounded-xl border border-white/[0.06] bg-black/35 p-4"
                  >
                    <p className="text-sm font-medium text-foreground">{row.templateName}</p>
                    <p className="text-xs text-muted-foreground">
                      {tDash("slotHint", {
                        location: row.locationName,
                        template: row.templateName,
                      })}
                    </p>
                    {row.stationLabel ? (
                      <p className="text-xs text-muted-foreground">
                        {tDash("stationLabel", { label: row.stationLabel })}
                      </p>
                    ) : null}
                    <Button
                      size="block"
                      variant="secondary"
                      className="rounded-xl bg-white/10"
                      disabled={claimingId !== null}
                      onClick={() => void handleClaimVacant(row)}
                    >
                      <PlayCircle className="size-5" />
                      {claimingId === row.id ? "…" : tDash("claimCta")}
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          <div className="so-glass rounded-2xl p-4">
            <p className="mb-2 font-medium text-foreground">{tDash("noShift")}</p>
            <p className="text-sm text-muted-foreground">{tDash("noShiftBody")}</p>
            <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
              {caps.canAccessAdminModules
                ? tDash("noShiftHintAdmin")
                : tDash("noShiftHintOperator")}
            </p>
          </div>
        </>
      ) : shift.status === "scheduled" ? (
        <div className="so-glass mb-3 rounded-2xl p-4">
          <div className="mb-3 flex items-center gap-2">
            <Clock3 className="h-5 w-5 text-primary" aria-hidden />
            <span className="font-medium text-foreground">{tDash("shiftStatus.scheduled")}</span>
          </div>
          <p className="mb-4 text-sm text-muted-foreground">
            {new Date(shift.scheduledStart).toLocaleString()} →{" "}
            {new Date(shift.scheduledEnd).toLocaleTimeString()}
          </p>
          <Button
            size="block"
            className={cn(primaryCtaClass)}
            onClick={() => void handleStart()}
            disabled={acting}
          >
            <PlayCircle className="size-5" />
            {tDash("startCta")}
          </Button>
        </div>
      ) : shift.status === "active" ? (
        <div className="so-glass mb-3 rounded-2xl p-4">
          <div className="mb-3 flex items-center justify-between">
            <span className="font-medium text-foreground">{tDash("shiftStatus.active")}</span>
            <span className="text-sm font-normal text-muted-foreground">{progress}%</span>
          </div>
          <Progress value={progress} className="mb-3" />
          <p className="text-sm text-muted-foreground">
            {done} / {total} {tDash("completed")} · {remaining} {tDash("remaining")}
          </p>
          {criticalLeft > 0 ? (
            <p className="text-sm text-critical mt-2">
              {tDash("criticalLeft", { count: criticalLeft })}
            </p>
          ) : null}
          <Button
            size="block"
            className={cn("mt-4", primaryCtaClass)}
            onClick={() => setView("tasks")}
          >
            <Sparkles className="size-5" />
            {tDash("continueCta")}
          </Button>
        </div>
      ) : (
        <div className="so-glass rounded-2xl p-4">
          <p className="mb-3 font-medium text-foreground">{tDash(`shiftStatus.${shift.status}`)}</p>
          <Button variant="secondary" size="block" className="rounded-2xl" onClick={() => setView("summary")}>
            {tDash("summaryCta")}
          </Button>
        </div>
      )}

      <p className="so-sec-title so-sec-flush mb-2 mt-8">{tDash("workSection.title")}</p>
      <GlassMenu>
        <GlassMenuRow
          icon={History}
          title={tHist("title")}
          subtitle={tDash("workSection.historySubtitle")}
          onClick={() => {
            haptic("light");
            setHistoryFilters(null);
            setView("history");
          }}
        />
        <GlassMenuRow
          icon={ArrowLeftRight}
          title={tSwap("openCta")}
          subtitle={tDash("workSection.swapSubtitle")}
          onClick={() => {
            haptic("light");
            setView("swapRequests");
          }}
        />
        <GlassMenuRow
          icon={Settings}
          title={tSettings("openCta")}
          subtitle={tDash("workSection.settingsSubtitle")}
          onClick={() => {
            haptic("light");
            setView("settings");
          }}
        />
      </GlassMenu>
    </main>
  );
}
