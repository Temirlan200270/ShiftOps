"use client";

import {
  ArrowLeft,
  BadgeCheck,
  Camera,
  CheckCircle2,
  Clock,
  ListChecks,
  ShieldAlert,
} from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { useShiftStore } from "@/lib/stores/shift-store";
import { SCORE_WEIGHTS, type ScoreBreakdown } from "@/lib/types";

interface SummaryScreenProps {
  onBack: () => void;
}

type ComponentKey = keyof ScoreBreakdown;

const COMPONENTS: ReadonlyArray<{
  key: ComponentKey;
  icon: React.ComponentType<{ className?: string }>;
}> = [
  { key: "completion", icon: ListChecks },
  { key: "criticalCompliance", icon: ShieldAlert },
  { key: "timeliness", icon: Clock },
  { key: "photoQuality", icon: Camera },
];

function pointsFor(component: ComponentKey, ratio: number): number {
  // Match server-side rounding (HALF_UP, two decimals) so the UI never
  // disagrees with the audit log on the displayed number.
  const raw = ratio * SCORE_WEIGHTS[component];
  return Math.round(raw * 100) / 100;
}

export function SummaryScreen({ onBack }: SummaryScreenProps): React.JSX.Element {
  const shift = useShiftStore((s) => s.shift);
  const tSum = useTranslations("summary");
  const tDash = useTranslations("dashboard");

  if (!shift) return <></>;

  const completed = shift.tasks.filter(
    (t) => t.status === "done" || t.status === "waived",
  ).length;
  const missed = shift.tasks.filter((t) => t.status === "skipped").length;
  const photos = shift.tasks.filter((t) => t.hasAttachment).length;

  return (
    <main className="mx-auto max-w-md px-4 pt-4 pb-24 animate-fade-in-up">
      <header className="flex items-center gap-3 mb-4">
        <Button variant="ghost" size="sm" onClick={onBack} className="-ml-2 px-2">
          <ArrowLeft className="size-5" />
        </Button>
        <h1 className="text-lg font-semibold flex-1">{tSum("title")}</h1>
      </header>

      <Card className="mb-4">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <BadgeCheck
              className={`size-6 ${
                shift.status === "closed_clean" ? "text-success" : "text-warning"
              }`}
            />
            {tDash(`shiftStatus.${shift.status}`)}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-3xl font-semibold">
            {shift.score !== null ? shift.score.toFixed(1) : "—"}
          </p>
          <p className="text-sm text-muted-foreground">{tSum("score")}</p>
          {shift.formulaVersion !== null ? (
            <p className="text-[11px] text-muted-foreground mt-1">
              {tSum("formulaVersion", { version: shift.formulaVersion })}
            </p>
          ) : null}
        </CardContent>
      </Card>

      {shift.scoreBreakdown ? (
        <Card className="mb-4">
          <CardHeader>
            <CardTitle className="text-base">{tSum("breakdownTitle")}</CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <p className="text-xs text-muted-foreground mb-3">
              {tSum("breakdownHelp", { max: 100 })}
            </p>
            <ul className="space-y-3">
              {COMPONENTS.map(({ key, icon: Icon }) => {
                const ratio = shift.scoreBreakdown![key];
                const points = pointsFor(key, ratio);
                const max = SCORE_WEIGHTS[key];
                return (
                  <li key={key}>
                    <div className="flex items-start gap-2 mb-1.5">
                      <Icon className="size-4 mt-0.5 text-muted-foreground shrink-0" />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-baseline justify-between gap-2">
                          <span className="text-sm font-medium">
                            {tSum(`components.${key}`)}
                          </span>
                          <span className="text-sm tabular-nums text-muted-foreground">
                            {points.toFixed(1)} / {max}
                          </span>
                        </div>
                        <p className="text-[11px] text-muted-foreground mt-0.5">
                          {tSum(`components.${key}Help`)}
                        </p>
                      </div>
                    </div>
                    <Progress value={ratio * 100} className="h-1.5" />
                  </li>
                );
              })}
            </ul>
          </CardContent>
        </Card>
      ) : null}

      <div className="grid grid-cols-3 gap-2">
        <Card>
          <CardContent className="p-3 flex flex-col items-center text-center">
            <CheckCircle2 className="size-5 text-success mb-1" />
            <p className="text-lg font-semibold">{completed}</p>
            <p className="text-xs text-muted-foreground">{tSum("completedTasks")}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-3 flex flex-col items-center text-center">
            <ShieldAlert className="size-5 text-critical mb-1" />
            <p className="text-lg font-semibold">{missed}</p>
            <p className="text-xs text-muted-foreground">{tSum("missedTasks")}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-3 flex flex-col items-center text-center">
            <Camera className="size-5 text-primary mb-1" />
            <p className="text-lg font-semibold">{photos}</p>
            <p className="text-xs text-muted-foreground">{tSum("photos")}</p>
          </CardContent>
        </Card>
      </div>

      <Button variant="secondary" size="block" className="mt-6" onClick={onBack}>
        {tSum("back")}
      </Button>
    </main>
  );
}
