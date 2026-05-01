"use client";

import {
  BarChart3,
  CalendarDays,
  Clock3,
  FileStack,
  History,
  PlayCircle,
  Radio,
  ScrollText,
  Settings,
  Sparkles,
  Upload,
  Users,
} from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { AnalyticsScreen } from "@/components/screens/analytics-screen";
import { AuditScreen } from "@/components/screens/audit-screen";
import { BusinessHoursScreen } from "@/components/screens/business-hours-screen";
import { CsvImportScreen } from "@/components/screens/csv-import-screen";
import { HistoryScreen, type HistoryFilters } from "@/components/screens/history-screen";
import { LiveMonitorScreen } from "@/components/screens/live-monitor-screen";
import { SettingsScreen } from "@/components/screens/settings-screen";
import { TaskListScreen } from "@/components/screens/task-list-screen";
import { SummaryScreen } from "@/components/screens/summary-screen";
import { TeamScreen } from "@/components/screens/team-screen";
import { TemplateEditScreen } from "@/components/screens/template-edit-screen";
import { TemplatesListScreen } from "@/components/screens/templates-list-screen";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import {
  claimShift,
  fetchAvailableShifts,
  fetchMyShift,
  readClientGeoForShiftStart,
  startShift,
  type VacantShift,
} from "@/lib/api/shifts";
import { localiseApiFailure } from "@/lib/i18n/api-errors";
import { useAuthStore } from "@/lib/stores/auth-store";
import { useShiftStore } from "@/lib/stores/shift-store";
import { toast } from "@/lib/stores/toast-store";
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
  | "team"
  | "settings";

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
  const tTpl = useTranslations("templates");
  const tA = useTranslations("analytics");
  const tCsv = useTranslations("csvImport");
  const tOrgBh = useTranslations("orgBusinessHours");
  const tLive = useTranslations("live");
  const tTeam = useTranslations("team");
  const tAudit = useTranslations("audit");
  const tSettings = useTranslations("settings");
  const role = useAuthStore((s) => s.me?.role ?? "operator");
  const isAdmin = role === "admin" || role === "owner";
  const [editingTemplateId, setEditingTemplateId] = React.useState<string | null>(null);
  const [historyFilters, setHistoryFilters] = React.useState<HistoryFilters | null>(null);

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
    // Intentionally mount-only: manual refreshes are triggered by user actions (start/close).
    // This avoids double refreshes under React 18 dev Strict Mode and keeps sub-screens steadier.
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Hooks must run on every render — declare here, before any early `return`
  // for sub-screens. Otherwise `react-hooks/rules-of-hooks` fails the build.
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
  if (view === "audit") {
    return <AuditScreen onBack={() => setView("dashboard")} />;
  }
  if (view === "templatesList" && isAdmin) {
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
  if (view === "templateEdit" && isAdmin) {
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
  if (view === "analytics" && isAdmin) {
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
  if (view === "csvImport" && isAdmin) {
    return <CsvImportScreen onBack={() => setView("dashboard")} />;
  }
  if (view === "businessHours" && isAdmin) {
    return <BusinessHoursScreen onBack={() => setView("dashboard")} />;
  }
  if (view === "liveMonitor" && isAdmin) {
    return <LiveMonitorScreen onBack={() => setView("dashboard")} />;
  }
  if (view === "team" && isAdmin) {
    return <TeamScreen onBack={() => setView("dashboard")} />;
  }
  if (view === "settings") {
    return <SettingsScreen onBack={() => setView("dashboard")} />;
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
      <header className="mb-6">
        <p className="text-sm text-muted-foreground">{new Date().toLocaleDateString()}</p>
        <h1 className="text-2xl font-semibold mt-1">{shift?.templateName ?? "ShiftOps"}</h1>
      </header>

      {loading && !shift ? (
        <Card className="animate-pulse">
          <CardContent className="p-6 h-40" />
        </Card>
      ) : !shift ? (
        <>
          {vacantShifts.length > 0 ? (
            <Card className="mb-3">
              <CardHeader>
                <CardTitle>{tDash("availableTitle")}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {vacantShifts.map((row) => (
                  <div
                    key={row.id}
                    className="flex flex-col gap-2 rounded-lg border border-border p-3 bg-elevated/40"
                  >
                    <p className="text-sm font-medium">{row.templateName}</p>
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
                      disabled={claimingId !== null}
                      onClick={() => void handleClaimVacant(row)}
                    >
                      <PlayCircle className="size-5" />
                      {claimingId === row.id ? "…" : tDash("claimCta")}
                    </Button>
                  </div>
                ))}
              </CardContent>
            </Card>
          ) : null}
          <Card>
            <CardHeader>
              <CardTitle>{tDash("noShift")}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">{tDash("noShiftBody")}</p>
            </CardContent>
          </Card>
        </>
      ) : shift.status === "scheduled" ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Clock3 className="size-5 text-primary" />
              {tDash("shiftStatus.scheduled")}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground mb-4">
              {new Date(shift.scheduledStart).toLocaleString()} → {" "}
              {new Date(shift.scheduledEnd).toLocaleTimeString()}
            </p>
            <Button size="block" onClick={handleStart} disabled={acting}>
              <PlayCircle className="size-5" />
              {tDash("startCta")}
            </Button>
          </CardContent>
        </Card>
      ) : shift.status === "active" ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <span>{tDash("shiftStatus.active")}</span>
              <span className="text-sm font-normal text-muted-foreground">{progress}%</span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Progress value={progress} className="mb-3" />
            <p className="text-sm text-muted-foreground">
              {done} / {total} {tDash("completed")} · {remaining} {tDash("remaining")}
            </p>
            {criticalLeft > 0 ? (
              <p className="text-sm text-critical mt-2">
                {tDash("criticalLeft", { count: criticalLeft })}
              </p>
            ) : null}
            <Button size="block" className="mt-4" onClick={() => setView("tasks")}>
              <Sparkles className="size-5" />
              {tDash("continueCta")}
            </Button>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>{tDash(`shiftStatus.${shift.status}`)}</CardTitle>
          </CardHeader>
          <CardContent>
            <Button variant="secondary" size="block" onClick={() => setView("summary")}>
              {tDash("summaryCta")}
            </Button>
          </CardContent>
        </Card>
      )}

      <Button
        variant="ghost"
        size="block"
        className="mt-3"
        onClick={() => setView("history")}
      >
        <History className="size-4" />
        {tHist("openHistoryCta")}
      </Button>

      <Button variant="ghost" size="block" className="mt-2" onClick={() => setView("settings")}>
        <Settings className="size-4" />
        {tSettings("openCta")}
      </Button>

      {isAdmin ? (
        <>
          <Button
            variant="ghost"
            size="block"
            className="mt-2"
            onClick={() => setView("team")}
          >
            <Users className="size-4" />
            {tTeam("openCta")}
          </Button>
          <Button
            variant="ghost"
            size="block"
            className="mt-2"
            onClick={() => setView("liveMonitor")}
          >
            <Radio className="size-4" />
            {tLive("openCta")}
          </Button>
          <Button
            variant="ghost"
            size="block"
            className="mt-2"
            onClick={() => setView("analytics")}
          >
            <BarChart3 className="size-4" />
            {tA("openCta")}
          </Button>
          <Button
            variant="ghost"
            size="block"
            className="mt-2"
            onClick={() => setView("businessHours")}
          >
            <CalendarDays className="size-4" />
            {tOrgBh("openCta")}
          </Button>
          <Button
            variant="ghost"
            size="block"
            className="mt-2"
            onClick={() => setView("csvImport")}
          >
            <Upload className="size-4" />
            {tCsv("openCta")}
          </Button>
          <Button
            variant="ghost"
            size="block"
            className="mt-2"
            onClick={() => {
              setEditingTemplateId(null);
              setView("templatesList");
            }}
          >
            <FileStack className="size-4" />
            {tTpl("openManageCta")}
          </Button>
          <Button
            variant="ghost"
            size="block"
            className="mt-2"
            onClick={() => setView("audit")}
          >
            <ScrollText className="size-4" />
            {tAudit("openCta")}
          </Button>
        </>
      ) : null}
    </main>
  );
}
