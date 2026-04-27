"use client";

import {
  BarChart3,
  Clock3,
  FileStack,
  History,
  PlayCircle,
  Radio,
  Sparkles,
  Upload,
} from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { AnalyticsScreen } from "@/components/screens/analytics-screen";
import { CsvImportScreen } from "@/components/screens/csv-import-screen";
import { HistoryScreen } from "@/components/screens/history-screen";
import { LiveMonitorScreen } from "@/components/screens/live-monitor-screen";
import { TaskListScreen } from "@/components/screens/task-list-screen";
import { SummaryScreen } from "@/components/screens/summary-screen";
import { TemplateEditScreen } from "@/components/screens/template-edit-screen";
import { TemplatesListScreen } from "@/components/screens/templates-list-screen";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { fetchMyShift, startShift } from "@/lib/api/shifts";
import { useAuthStore } from "@/lib/stores/auth-store";
import { useShiftStore } from "@/lib/stores/shift-store";
import { toast } from "@/lib/stores/toast-store";
import { haptic, notify } from "@/lib/telegram/init";

type View =
  | "dashboard"
  | "tasks"
  | "summary"
  | "history"
  | "templatesList"
  | "templateEdit"
  | "analytics"
  | "csvImport"
  | "liveMonitor";

export function DashboardScreen(): React.JSX.Element {
  const shift = useShiftStore((s) => s.shift);
  const setShift = useShiftStore((s) => s.setShift);
  const [view, setView] = React.useState<View>("dashboard");
  const [loading, setLoading] = React.useState(true);
  const [acting, setActing] = React.useState(false);
  const tDash = useTranslations("dashboard");
  const tErr = useTranslations("errors");
  const tHist = useTranslations("history");
  const tTpl = useTranslations("templates");
  const tA = useTranslations("analytics");
  const tCsv = useTranslations("csvImport");
  const tLive = useTranslations("live");
  const role = useAuthStore((s) => s.me?.role ?? "operator");
  const isAdmin = role === "admin" || role === "owner";
  const [editingTemplateId, setEditingTemplateId] = React.useState<string | null>(null);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    const result = await fetchMyShift();
    if (result.ok) {
      setShift(result.data);
    } else {
      toast({ variant: "critical", title: tErr("generic"), description: result.message });
    }
    setLoading(false);
  }, [setShift, tErr]);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  // Hooks must run on every render — declare here, before any early `return`
  // for sub-screens. Otherwise `react-hooks/rules-of-hooks` fails the build.
  const handleStart = React.useCallback(async () => {
    if (!shift) return;
    setActing(true);
    haptic("medium");
    const result = await startShift(shift.id);
    setActing(false);
    if (result.ok) {
      setShift(result.data);
      notify("success");
      setView("tasks");
    } else {
      notify("error");
      toast({ variant: "critical", title: tErr("generic"), description: result.message });
    }
  }, [shift, setShift, tErr]);

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
    return <HistoryScreen onBack={() => setView("dashboard")} />;
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
    return <AnalyticsScreen onBack={() => setView("dashboard")} />;
  }
  if (view === "csvImport" && isAdmin) {
    return <CsvImportScreen onBack={() => setView("dashboard")} />;
  }
  if (view === "liveMonitor" && isAdmin) {
    return <LiveMonitorScreen onBack={() => setView("dashboard")} />;
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
        <Card>
          <CardHeader>
            <CardTitle>{tDash("noShift")}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">{tDash("noShiftBody")}</p>
          </CardContent>
        </Card>
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

      {isAdmin ? (
        <>
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
        </>
      ) : null}
    </main>
  );
}
