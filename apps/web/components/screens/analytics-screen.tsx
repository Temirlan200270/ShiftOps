"use client";

/**
 * Owner / admin analytics dashboard (S9).
 *
 * One screen, four cards
 * ----------------------
 * The whole screen sources from a single ``/v1/analytics/overview``
 * call; everything below is presentational. Three rendering decisions
 * worth flagging:
 *
 * 1. **Heatmap** is a pure CSS grid (7 rows × 24 cols). No chart lib —
 *    saves ~25 KB and renders crisp at any pixel ratio. Cell shade is
 *    a HSL ramp from "very low score = red" → "very high = green",
 *    with empty slots rendered as a hatched divider so the eye doesn't
 *    confuse "no data" with "zero score".
 * 2. **Top violators / locations** are simple Card lists, sorted on
 *    the server. Frontend sort would let admins fool themselves with
 *    a different ordering for screenshots; we don't allow it.
 * 3. **Loading** uses a pulse skeleton that matches the final layout
 *    so the page doesn't reflow on first paint.
 */

import { ArrowLeft, BarChart3, MapPin, ShieldAlert, Users } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import {
  fetchOverview,
  type AnalyticsHeatmapCell,
  type AnalyticsOverview,
} from "@/lib/api/analytics";
import { toast } from "@/lib/stores/toast-store";

interface AnalyticsScreenProps {
  onBack: () => void;
}

const RANGES = [7, 30, 90] as const;
type Range = (typeof RANGES)[number];

function scoreColor(score: number | null): string {
  if (score === null) return "text-muted-foreground";
  if (score >= 90) return "text-success";
  if (score >= 70) return "text-foreground";
  if (score >= 50) return "text-warning";
  return "text-critical";
}

/**
 * Pick a background tint for a heatmap cell. We linear-interpolate hue
 * inside the warning→success range so a glance at the grid acts as a
 * Likert scale. We avoid 0–360° because that would wrap red→pink for
 * very high scores, which would read as "alarm" not "good".
 */
function heatmapCellStyle(score: number | null): React.CSSProperties {
  if (score === null) {
    return {
      backgroundImage:
        "repeating-linear-gradient(45deg, hsl(var(--border) / 0.4) 0 4px, transparent 4px 8px)",
    };
  }
  const clamped = Math.max(0, Math.min(100, score));
  // 0 → red (10°), 60 → amber (45°), 100 → green (140°). Lightness adapts
  // to the score so very low cells aren't unreadable on dark backgrounds.
  const hue = 10 + (clamped / 100) * 130;
  const saturation = 70;
  const lightness = clamped < 60 ? 38 : 32;
  const alpha = 0.35 + (clamped / 100) * 0.45;
  return { backgroundColor: `hsla(${hue}, ${saturation}%, ${lightness}%, ${alpha})` };
}

function formatScore(score: number | null): string {
  if (score === null) return "—";
  return score.toFixed(1);
}

function indexHeatmap(cells: AnalyticsHeatmapCell[]): Map<string, AnalyticsHeatmapCell> {
  const idx = new Map<string, AnalyticsHeatmapCell>();
  for (const c of cells) idx.set(`${c.dayOfWeek}:${c.hourOfDay}`, c);
  return idx;
}

function HeatmapGrid({
  cells,
  emptyLabel,
  dayLabels,
}: {
  cells: AnalyticsHeatmapCell[];
  emptyLabel: string;
  dayLabels: string[];
}): React.JSX.Element {
  const indexed = React.useMemo(() => indexHeatmap(cells), [cells]);
  if (cells.length === 0) {
    return (
      <div className="text-center py-8 text-sm text-muted-foreground">{emptyLabel}</div>
    );
  }

  // Show only the four six-hour ticks so the bottom axis stays legible
  // on a 360 px viewport. Power users on tablet can still hover for the
  // numeric tooltip via title attribute.
  const hourTicks = [0, 6, 12, 18];

  return (
    <div className="overflow-x-auto -mx-4 px-4">
      <div className="min-w-[480px]">
        <div className="grid grid-cols-[28px_repeat(24,minmax(14px,1fr))] gap-[2px]">
          <div />
          {Array.from({ length: 24 }, (_, h) => (
            <div
              key={`hh-${h}`}
              className="text-[9px] text-muted-foreground text-center tabular-nums"
            >
              {hourTicks.includes(h) ? h.toString().padStart(2, "0") : ""}
            </div>
          ))}

          {dayLabels.map((label, day) => (
            <React.Fragment key={`row-${day}`}>
              <div className="text-[10px] text-muted-foreground self-center">{label}</div>
              {Array.from({ length: 24 }, (_, hour) => {
                const cell = indexed.get(`${day}:${hour}`);
                const score = cell?.averageScore ?? null;
                const tooltip =
                  cell === undefined
                    ? `${label} ${hour}:00 — —`
                    : `${label} ${hour}:00 — ${formatScore(score)}`;
                return (
                  <div
                    key={`c-${day}-${hour}`}
                    title={tooltip}
                    style={heatmapCellStyle(score)}
                    className="h-5 rounded-[3px] border border-border/40"
                  />
                );
              })}
            </React.Fragment>
          ))}
        </div>
      </div>
    </div>
  );
}

function KpiCard({
  label,
  value,
  emphasis = "default",
}: {
  label: string;
  value: string;
  emphasis?: "default" | "warning" | "success";
}): React.JSX.Element {
  const color =
    emphasis === "warning"
      ? "text-warning"
      : emphasis === "success"
        ? "text-success"
        : "text-foreground";
  return (
    <Card>
      <CardContent className="p-3">
        <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
        <p className={`text-xl font-semibold tabular-nums mt-1 ${color}`}>{value}</p>
      </CardContent>
    </Card>
  );
}

export function AnalyticsScreen({ onBack }: AnalyticsScreenProps): React.JSX.Element {
  const tA = useTranslations("analytics");
  const tErr = useTranslations("errors");

  const [range, setRange] = React.useState<Range>(30);
  const [data, setData] = React.useState<AnalyticsOverview | null>(null);
  const [loading, setLoading] = React.useState(true);

  const load = React.useCallback(
    async (days: Range) => {
      setLoading(true);
      const result = await fetchOverview({ days });
      if (result.ok) {
        setData(result.data);
      } else {
        toast({ variant: "critical", title: tErr("generic"), description: result.message });
      }
      setLoading(false);
    },
    [tErr],
  );

  React.useEffect(() => {
    void load(range);
  }, [load, range]);

  const dayLabels = React.useMemo(() => {
    const raw = tA.raw("heatmap.days") as unknown;
    if (Array.isArray(raw)) return raw as string[];
    return ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  }, [tA]);

  const kpis = data?.kpis;
  const cleanlinessPct =
    kpis?.cleanlinessRate === null || kpis?.cleanlinessRate === undefined
      ? null
      : Math.round(kpis.cleanlinessRate * 100);

  return (
    <main className="mx-auto max-w-md px-4 pt-4 pb-24 animate-fade-in-up">
      <header className="flex items-center gap-3 mb-4">
        <Button variant="ghost" size="sm" onClick={onBack} className="-ml-2 px-2">
          <ArrowLeft className="size-5" />
        </Button>
        <div className="flex-1">
          <h1 className="text-lg font-semibold">{tA("title")}</h1>
          <p className="text-xs text-muted-foreground">{tA("subtitleDays", { days: range })}</p>
        </div>
      </header>

      <div className="flex gap-2 mb-4">
        {RANGES.map((r) => (
          <button
            key={r}
            type="button"
            onClick={() => setRange(r)}
            className={
              "flex-1 h-9 rounded-md text-sm font-medium transition border " +
              (r === range
                ? "bg-primary text-primary-foreground border-primary"
                : "bg-elevated text-foreground border-border hover:bg-elevated/80")
            }
          >
            {tA(`ranges.${r}`)}
          </button>
        ))}
      </div>

      {loading && !data ? (
        <Card className="animate-pulse">
          <CardContent className="p-6 h-40" />
        </Card>
      ) : !data || data.kpis.shiftsClosed === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <BarChart3 className="size-5 text-muted-foreground" />
              {tA("empty")}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">{tA("emptyHint")}</p>
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2 mb-4">
            <KpiCard
              label={tA("kpis.shiftsClosed")}
              value={data.kpis.shiftsClosed.toString()}
            />
            <KpiCard
              label={tA("kpis.averageScore")}
              value={formatScore(data.kpis.averageScore)}
              emphasis={
                (data.kpis.averageScore ?? 0) >= 90
                  ? "success"
                  : (data.kpis.averageScore ?? 0) < 70
                    ? "warning"
                    : "default"
              }
            />
            <KpiCard
              label={tA("kpis.shiftsClean")}
              value={data.kpis.shiftsClean.toString()}
              emphasis="success"
            />
            <KpiCard
              label={tA("kpis.shiftsWithViolations")}
              value={data.kpis.shiftsWithViolations.toString()}
              emphasis={data.kpis.shiftsWithViolations > 0 ? "warning" : "default"}
            />
          </div>

          {cleanlinessPct !== null ? (
            <Card className="mb-4">
              <CardContent className="p-4">
                <div className="flex items-baseline justify-between mb-2">
                  <p className="text-xs text-muted-foreground uppercase tracking-wide">
                    {tA("kpis.cleanlinessRate")}
                  </p>
                  <p className={`text-base font-semibold tabular-nums ${scoreColor(cleanlinessPct)}`}>
                    {cleanlinessPct}%
                  </p>
                </div>
                <Progress value={cleanlinessPct} />
              </CardContent>
            </Card>
          ) : null}

          <Card className="mb-4">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <BarChart3 className="size-4 text-primary" />
                {tA("heatmap.title")}
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-1">
              <HeatmapGrid
                cells={data.heatmap}
                emptyLabel={tA("heatmap.noData")}
                dayLabels={dayLabels}
              />
              <p className="text-[10px] text-muted-foreground mt-3">{tA("heatmap.help")}</p>
            </CardContent>
          </Card>

          <Card className="mb-4">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Users className="size-4 text-warning" />
                {tA("violators.title")}
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-1">
              {data.topViolators.length === 0 ? (
                <p className="text-sm text-muted-foreground">{tA("violators.empty")}</p>
              ) : (
                <ul className="space-y-2">
                  {data.topViolators.map((v) => (
                    <li
                      key={v.userId}
                      className="flex items-center gap-3 p-2 -mx-2 rounded-md bg-elevated/40"
                    >
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium truncate">{v.fullName}</p>
                        <p className="text-[11px] text-muted-foreground">
                          {tA("violators.shiftsTotal", { count: v.shiftsTotal })} ·{" "}
                          {tA("violators.violations", { count: v.shiftsWithViolations })}
                        </p>
                      </div>
                      <div className="text-right">
                        <p
                          className={`text-base font-semibold tabular-nums ${scoreColor(v.averageScore)}`}
                        >
                          {formatScore(v.averageScore)}
                        </p>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
              <p className="text-[10px] text-muted-foreground mt-3">{tA("violators.help")}</p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <MapPin className="size-4 text-primary" />
                {tA("locations.title")}
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-1">
              {data.locations.length === 0 ? (
                <p className="text-sm text-muted-foreground">{tA("locations.noData")}</p>
              ) : (
                <ul className="space-y-2">
                  {data.locations.map((loc) => (
                    <li
                      key={loc.locationId}
                      className="flex items-center gap-3 p-2 -mx-2 rounded-md hover:bg-elevated/40"
                    >
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium truncate">{loc.locationName}</p>
                        <p className="text-[11px] text-muted-foreground">
                          {tA("locations.shifts", { count: loc.shiftsTotal })}
                          {loc.shiftsWithViolations > 0 ? (
                            <>
                              {" "}
                              ·{" "}
                              <span className="text-warning inline-flex items-center gap-0.5">
                                <ShieldAlert className="size-3" />
                                {tA("locations.violations", {
                                  count: loc.shiftsWithViolations,
                                })}
                              </span>
                            </>
                          ) : null}
                        </p>
                      </div>
                      <p
                        className={`text-base font-semibold tabular-nums ${scoreColor(loc.averageScore)}`}
                      >
                        {formatScore(loc.averageScore)}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </main>
  );
}
