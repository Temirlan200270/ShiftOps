"use client";

/**
 * Owner / admin analytics dashboard (S9 v2).
 *
 * One screen, many cards
 * ----------------------
 * The whole screen sources from a single ``/v1/analytics/overview``
 * call; everything below is presentational. Three rendering decisions
 * worth flagging:
 *
 * 1. **Heatmap** is a pure CSS grid (7 rows × 24 cols). No chart lib —
 *    saves ~25 KB and renders crisp at any pixel ratio.
 * 2. **Top violators / locations / templates** are simple Card lists,
 *    sorted on the server. Frontend sort would let admins fool themselves
 *    with a different ordering for screenshots.
 * 3. **Density flags** drive a "Few data points" hint on each block so
 *    the dashboard stays honest at low N — see ``analytics.lowData.*``.
 *
 * Compare mode renders KPI tiles with a previous-period strip and a delta
 * arrow. We deliberately keep the delta semantics simple (just "more" /
 * "less" with a colour) so the operator who grew "with violations" by 30%
 * can't misread it as a green improvement.
 */

import {
  ArrowLeft,
  BarChart3,
  CalendarRange,
  ChevronRight,
  Layers,
  MapPin,
  Radio,
  ShieldAlert,
  ShieldCheck,
  Timer,
  Users,
} from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { OperatorProfileSheet } from "@/components/screens/operator-profile-sheet";
import type { HistoryFilters } from "@/components/screens/history-screen";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import {
  fetchOverview,
  type AnalyticsHeatmapCell,
  type AnalyticsKpi,
  type AnalyticsOverview,
  type AnalyticsViolator,
  type DensityFlag,
} from "@/lib/api/analytics";
import { fetchLocations, type LocationRow } from "@/lib/api/locations";
import { toast } from "@/lib/stores/toast-store";

interface AnalyticsScreenProps {
  onBack: () => void;
  /**
   * Open the history screen pre-filtered. Provided by the parent so the
   * single-route navigation stays in DashboardScreen — see CLAUDE.md.
   */
  onOpenInHistory?: (filters: HistoryFilters) => void;
}

const PRESETS = [7, 30, 90] as const;
type Preset = (typeof PRESETS)[number];

/**
 * Postgres / API `day_of_week` matches `EXTRACT(DOW)`: 0=Sun .. 6=Sat.
 * We render the grid Mon→Sun (ISO / business week) for readability.
 */
const HEATMAP_ROW_DOW = [1, 2, 3, 4, 5, 6, 0] as const;

const VIOLATORS_LIMIT = 10;

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

function scoreColor(score: number | null): string {
  if (score === null) return "text-muted-foreground";
  if (score >= 90) return "text-success";
  if (score >= 70) return "text-foreground";
  if (score >= 50) return "text-warning";
  return "text-critical";
}

function heatmapCellStyle(score: number | null): React.CSSProperties {
  if (score === null) {
    return {
      backgroundImage:
        "repeating-linear-gradient(45deg, hsl(var(--border) / 0.4) 0 4px, transparent 4px 8px)",
    };
  }
  const clamped = Math.max(0, Math.min(100, score));
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

/** ISO date YYYY-MM-DD (UTC). */
function toIsoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function presetWindow(preset: Preset): { from: string; to: string } {
  const now = new Date();
  const from = new Date(now.getTime() - preset * 86400_000);
  return { from: toIsoDate(from), to: toIsoDate(now) };
}

function clampInt(value: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, value));
}

function parseIsoDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const d = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(d.getTime()) ? null : d;
}

function diffDays(from: string, to: string): number {
  const fromD = parseIsoDate(from);
  const toD = parseIsoDate(to);
  if (!fromD || !toD) return 0;
  return Math.round((toD.getTime() - fromD.getTime()) / 86400_000);
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

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

          {dayLabels.map((label, rowIdx) => {
            const dayOfWeek = HEATMAP_ROW_DOW[rowIdx] ?? 0;
            return (
              <React.Fragment key={`row-${dayOfWeek}`}>
                <div className="text-[10px] text-muted-foreground self-center">{label}</div>
                {Array.from({ length: 24 }, (_, hour) => {
                  const cell = indexed.get(`${dayOfWeek}:${hour}`);
                  const score = cell?.averageScore ?? null;
                  const tooltip =
                    cell === undefined
                      ? `${label} ${hour}:00 — —`
                      : `${label} ${hour}:00 — ${formatScore(score)}`;
                  return (
                    <div
                      key={`c-${dayOfWeek}-${hour}`}
                      title={tooltip}
                      style={heatmapCellStyle(score)}
                      className="h-5 rounded-[3px] border border-border/40"
                    />
                  );
                })}
              </React.Fragment>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function KpiCard({
  label,
  value,
  emphasis = "default",
  previous,
  delta,
  previousLabel,
}: {
  label: string;
  value: string;
  emphasis?: "default" | "warning" | "success";
  previous?: string;
  delta?: { value: string; direction: "up" | "down" | "flat"; tone: "good" | "bad" | "neutral" };
  previousLabel?: string;
}): React.JSX.Element {
  const color =
    emphasis === "warning"
      ? "text-warning"
      : emphasis === "success"
        ? "text-success"
        : "text-foreground";
  const deltaColor =
    delta?.tone === "good"
      ? "text-success"
      : delta?.tone === "bad"
        ? "text-critical"
        : "text-muted-foreground";
  return (
    <Card>
      <CardContent className="p-3">
        <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
        <p className={`text-xl font-semibold tabular-nums mt-1 ${color}`}>{value}</p>
        {previous !== undefined ? (
          <div className="mt-1 flex items-baseline justify-between gap-2 text-[10px] text-muted-foreground">
            <span>
              {previousLabel ?? "Prev"}: <span className="tabular-nums">{previous}</span>
            </span>
            {delta ? (
              <span className={`tabular-nums ${deltaColor}`}>
                {delta.direction === "up" ? "▲" : delta.direction === "down" ? "▼" : "▬"}{" "}
                {delta.value}
              </span>
            ) : null}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function LowDataNote({ flag, message }: { flag: DensityFlag; message: string }): React.JSX.Element | null {
  if (flag !== "low") return null;
  return (
    <div className="mt-2 flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 px-2.5 py-1.5">
      <ShieldAlert className="size-3.5 mt-[2px] text-warning shrink-0" />
      <p className="text-[11px] text-warning leading-snug">{message}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Date-range picker (sheet)
// ---------------------------------------------------------------------------

function CustomRangeSheet({
  open,
  onOpenChange,
  initialFrom,
  initialTo,
  onApply,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialFrom: string;
  initialTo: string;
  onApply: (from: string, to: string) => void;
}): React.JSX.Element {
  const t = useTranslations("analytics.customRange");
  const [from, setFrom] = React.useState(initialFrom);
  const [to, setTo] = React.useState(initialTo);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (open) {
      setFrom(initialFrom);
      setTo(initialTo);
      setError(null);
    }
  }, [open, initialFrom, initialTo]);

  const submit = (): void => {
    if (!from || !to) {
      setError(t("invalid"));
      return;
    }
    if (to < from) {
      setError(t("invalid"));
      return;
    }
    if (diffDays(from, to) > 365) {
      setError(t("tooLong"));
      return;
    }
    setError(null);
    onApply(from, to);
    onOpenChange(false);
  };

  // `modal={false}`: Radix modal mode locks `document.body` scroll and adds
  // scrollbar-gutter compensation; in Telegram WebView that often produces a
  // visible "jump" of the header buttons when the sheet closes (Cancel).
  return (
    <Sheet modal={false} open={open} onOpenChange={onOpenChange}>
      <SheetContent title={t("title")}>
        <div className="grid grid-cols-2 gap-3 mt-2">
          <label className="block text-xs">
            <span className="text-muted-foreground">{t("from")}</span>
            <input
              type="date"
              value={from}
              onChange={(e) => setFrom(e.target.value)}
              className="mt-1 w-full rounded-md border border-border bg-elevated px-2 py-1.5 text-sm"
            />
          </label>
          <label className="block text-xs">
            <span className="text-muted-foreground">{t("to")}</span>
            <input
              type="date"
              value={to}
              onChange={(e) => setTo(e.target.value)}
              className="mt-1 w-full rounded-md border border-border bg-elevated px-2 py-1.5 text-sm"
            />
          </label>
        </div>
        {error ? <p className="text-xs text-critical mt-2">{error}</p> : null}
        <div className="mt-4 flex gap-2">
          <Button
            variant="ghost"
            className="flex-1"
            onClick={() => onOpenChange(false)}
          >
            {t("cancel")}
          </Button>
          <Button onClick={submit} className="flex-1">
            {t("apply")}
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}

// ---------------------------------------------------------------------------
// Main screen
// ---------------------------------------------------------------------------

interface RangeState {
  preset: Preset | "custom";
  from: string;
  to: string;
}

export function AnalyticsScreen({
  onBack,
  onOpenInHistory,
}: AnalyticsScreenProps): React.JSX.Element {
  const tA = useTranslations("analytics");
  const tErr = useTranslations("errors");

  const [range, setRange] = React.useState<RangeState>(() => {
    const win = presetWindow(30);
    return { preset: 30, from: win.from, to: win.to };
  });
  const [compare, setCompare] = React.useState(false);
  const [data, setData] = React.useState<AnalyticsOverview | null>(null);
  const [loading, setLoading] = React.useState(true);

  const [locations, setLocations] = React.useState<LocationRow[] | null>(null);
  const [locationId, setLocationId] = React.useState<string | null>(null);

  const [customOpen, setCustomOpen] = React.useState(false);

  const [violator, setViolator] = React.useState<AnalyticsViolator | null>(null);
  const [violatorOpen, setViolatorOpen] = React.useState(false);

  // Locations are static across this session (org doesn't change), so a
  // single fetch on mount is enough. We tolerate failure quietly — the
  // selector just hides itself.
  React.useEffect(() => {
    let cancelled = false;
    void fetchLocations().then((res) => {
      if (cancelled) return;
      if (res.ok) setLocations(res.data);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const load = React.useCallback(
    async (state: RangeState, withCompare: boolean, locId: string | null) => {
      setLoading(true);
      const result = await fetchOverview({
        from: state.from,
        to: state.to,
        compare: withCompare,
        violatorsLimit: VIOLATORS_LIMIT,
        locationId: locId,
      });
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
    void load(range, compare, locationId);
  }, [load, range, compare, locationId]);

  const dayLabels = React.useMemo(() => {
    const raw = tA.raw("heatmap.days") as
      | Record<string, string>
      | string[]
      | undefined;
    if (raw && typeof raw === "object" && !Array.isArray(raw)) {
      return HEATMAP_ROW_DOW.map((dow) => raw[String(dow)] ?? "");
    }
    if (Array.isArray(raw) && raw.length === 7) {
      return HEATMAP_ROW_DOW.map((dow) => raw[dow] ?? "");
    }
    return ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  }, [tA]);

  const kpis = data?.kpis;
  const cleanlinessPct =
    kpis?.cleanlinessRate === null || kpis?.cleanlinessRate === undefined
      ? null
      : Math.round(kpis.cleanlinessRate * 100);

  const previous = data?.previous ?? null;
  const showLocationPicker = (locations?.length ?? 0) > 1;

  const subtitle = (() => {
    if (range.preset !== "custom") {
      return tA("subtitleDays", { days: range.preset });
    }
    return tA("subtitleRange", { from: range.from, to: range.to });
  })();

  const onViolatorClick = (v: AnalyticsViolator): void => {
    setViolator(v);
    setViolatorOpen(true);
  };

  const onOpenViolatorInHistory = (): void => {
    if (!violator || !onOpenInHistory) return;
    onOpenInHistory({
      userId: violator.userId,
      userName: violator.fullName,
      locationId,
      locationName:
        locations?.find((l) => l.id === locationId)?.name ?? null,
      from: range.from,
      to: range.to,
    });
  };

  return (
    <main className="mx-auto max-w-md px-4 pt-4 pb-24 animate-fade-in-up">
      <header className="flex items-center gap-3 mb-4">
        <Button variant="ghost" size="sm" onClick={onBack} className="-ml-2 px-2">
          <ArrowLeft className="size-5" />
        </Button>
        <div className="flex-1">
          <h1 className="text-lg font-semibold">{tA("title")}</h1>
          <p className="text-xs text-muted-foreground">{subtitle}</p>
        </div>
      </header>

      <div className="flex shrink-0 flex-nowrap gap-2 overflow-x-auto pb-0.5 mb-2">
        {PRESETS.map((p) => (
          <button
            key={p}
            type="button"
            onClick={() => {
              const win = presetWindow(p);
              setRange({ preset: p, from: win.from, to: win.to });
            }}
            className={
              "flex-1 h-9 rounded-md text-sm font-medium transition border " +
              (range.preset === p
                ? "bg-primary text-primary-foreground border-primary"
                : "bg-elevated text-foreground border-border hover:bg-elevated/80")
            }
          >
            {tA(`ranges.${p}`)}
          </button>
        ))}
        <button
          type="button"
          onClick={() => setCustomOpen(true)}
          className={
            "flex-1 h-9 rounded-md text-sm font-medium transition border inline-flex items-center justify-center gap-1 " +
            (range.preset === "custom"
              ? "bg-primary text-primary-foreground border-primary"
              : "bg-elevated text-foreground border-border hover:bg-elevated/80")
          }
        >
          <CalendarRange className="size-4" />
          {tA("ranges.custom")}
        </button>
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <label className="inline-flex items-center gap-2 text-xs text-muted-foreground select-none">
          <input
            type="checkbox"
            checked={compare}
            onChange={(e) => setCompare(e.target.checked)}
            className="size-4 rounded border-border bg-elevated"
          />
          {tA("compare.label")}
        </label>

        {showLocationPicker ? (
          <label className="ml-auto inline-flex items-center gap-2 text-xs text-muted-foreground">
            <span>{tA("filters.locationLabel")}</span>
            <select
              value={locationId ?? ""}
              onChange={(e) => setLocationId(e.target.value || null)}
              className="rounded-md border border-border bg-elevated px-2 py-1 text-xs text-foreground"
            >
              <option value="">{tA("filters.locationAll")}</option>
              {(locations ?? []).map((loc) => (
                <option key={loc.id} value={loc.id}>
                  {loc.name}
                </option>
              ))}
            </select>
          </label>
        ) : null}
      </div>

      <CustomRangeSheet
        open={customOpen}
        onOpenChange={setCustomOpen}
        initialFrom={range.from}
        initialTo={range.to}
        onApply={(from, to) => {
          setRange({ preset: "custom", from, to });
        }}
      />

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
          <KpiGrid
            kpis={data.kpis}
            previousKpis={previous?.kpis ?? null}
            previousLabel={tA("compare.previousLabel")}
            labels={{
              shiftsClosed: tA("kpis.shiftsClosed"),
              averageScore: tA("kpis.averageScore"),
              shiftsClean: tA("kpis.shiftsClean"),
              shiftsWithViolations: tA("kpis.shiftsWithViolations"),
            }}
          />

          <LowDataNote flag={data.density?.kpis ?? "ok"} message={tA("lowData.kpis")} />

          {cleanlinessPct !== null ? (
            <Card className="mb-4 mt-3">
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
              <LowDataNote
                flag={data.density?.heatmap ?? "ok"}
                message={tA("lowData.heatmap")}
              />
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
                    <li key={v.userId}>
                      <button
                        type="button"
                        onClick={() => onViolatorClick(v)}
                        className="w-full flex items-center gap-3 p-2 -mx-2 rounded-md bg-elevated/40 hover:bg-elevated text-left"
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
                        <ChevronRight className="size-4 text-muted-foreground shrink-0" />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <p className="text-[10px] text-muted-foreground mt-3">{tA("violators.help")}</p>
              <LowDataNote
                flag={data.density?.violators ?? "ok"}
                message={tA("lowData.violators")}
              />
            </CardContent>
          </Card>

          <LocationsCard
            data={data}
            tTitle={tA("locations.title")}
            tNoData={tA("locations.noData")}
            tShifts={(count) => tA("locations.shifts", { count })}
            tViolations={(count) => tA("locations.violations", { count })}
          />

          <TemplatesCard data={data} />

          <CriticalityCard data={data} />

          <RoleSplitCard data={data} />

          <SlaCard data={data} />

          <AntifakeCard data={data} />
        </>
      )}

      <OperatorProfileSheet
        open={violatorOpen}
        operator={violator}
        rangeFrom={range.from}
        rangeTo={range.to}
        locationId={locationId}
        onOpenChange={setViolatorOpen}
        onOpenInHistory={onOpenViolatorInHistory}
      />
    </main>
  );
}

// ---------------------------------------------------------------------------
// KPI grid (with compare deltas)
// ---------------------------------------------------------------------------

interface DeltaInfo {
  value: string;
  direction: "up" | "down" | "flat";
  tone: "good" | "bad" | "neutral";
}

function deltaCount(
  current: number,
  previous: number | null | undefined,
  options: { invert?: boolean } = {},
): DeltaInfo | undefined {
  if (previous === null || previous === undefined) return undefined;
  const diff = current - previous;
  if (diff === 0) return { value: "0", direction: "flat", tone: "neutral" };
  const direction = diff > 0 ? "up" : "down";
  const goodDirection = options.invert ? "down" : "up";
  return {
    value: String(Math.abs(diff)),
    direction,
    tone: direction === goodDirection ? "good" : "bad",
  };
}

function deltaScore(
  current: number | null,
  previous: number | null | undefined,
): DeltaInfo | undefined {
  if (current === null || previous === null || previous === undefined) return undefined;
  const diff = current - previous;
  if (Math.abs(diff) < 0.05) return { value: "0.0", direction: "flat", tone: "neutral" };
  return {
    value: Math.abs(diff).toFixed(1),
    direction: diff > 0 ? "up" : "down",
    tone: diff > 0 ? "good" : "bad",
  };
}

function KpiGrid({
  kpis,
  previousKpis,
  previousLabel,
  labels,
}: {
  kpis: AnalyticsKpi;
  previousKpis: AnalyticsKpi | null;
  previousLabel: string;
  labels: {
    shiftsClosed: string;
    averageScore: string;
    shiftsClean: string;
    shiftsWithViolations: string;
  };
}): React.JSX.Element {
  return (
    <div className="grid grid-cols-2 gap-2">
      <KpiCard
        label={labels.shiftsClosed}
        value={kpis.shiftsClosed.toString()}
        previous={previousKpis ? previousKpis.shiftsClosed.toString() : undefined}
        delta={deltaCount(kpis.shiftsClosed, previousKpis?.shiftsClosed)}
        previousLabel={previousLabel}
      />
      <KpiCard
        label={labels.averageScore}
        value={formatScore(kpis.averageScore)}
        emphasis={
          (kpis.averageScore ?? 0) >= 90
            ? "success"
            : (kpis.averageScore ?? 0) < 70
              ? "warning"
              : "default"
        }
        previous={
          previousKpis ? formatScore(previousKpis.averageScore) : undefined
        }
        delta={deltaScore(kpis.averageScore, previousKpis?.averageScore)}
        previousLabel={previousLabel}
      />
      <KpiCard
        label={labels.shiftsClean}
        value={kpis.shiftsClean.toString()}
        emphasis="success"
        previous={previousKpis ? previousKpis.shiftsClean.toString() : undefined}
        delta={deltaCount(kpis.shiftsClean, previousKpis?.shiftsClean)}
        previousLabel={previousLabel}
      />
      <KpiCard
        label={labels.shiftsWithViolations}
        value={kpis.shiftsWithViolations.toString()}
        emphasis={kpis.shiftsWithViolations > 0 ? "warning" : "default"}
        previous={
          previousKpis ? previousKpis.shiftsWithViolations.toString() : undefined
        }
        // Inverse semantics: more violations = bad (red).
        delta={deltaCount(kpis.shiftsWithViolations, previousKpis?.shiftsWithViolations, {
          invert: true,
        })}
        previousLabel={previousLabel}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Existing block: locations
// ---------------------------------------------------------------------------

function LocationsCard({
  data,
  tTitle,
  tNoData,
  tShifts,
  tViolations,
}: {
  data: AnalyticsOverview;
  tTitle: string;
  tNoData: string;
  tShifts: (count: number) => string;
  tViolations: (count: number) => string;
}): React.JSX.Element {
  return (
    <Card className="mb-4">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <MapPin className="size-4 text-primary" />
          {tTitle}
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-1">
        {data.locations.length === 0 ? (
          <p className="text-sm text-muted-foreground">{tNoData}</p>
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
                    {tShifts(loc.shiftsTotal)}
                    {loc.shiftsWithViolations > 0 ? (
                      <>
                        {" "}
                        ·{" "}
                        <span className="text-warning inline-flex items-center gap-0.5">
                          <ShieldAlert className="size-3" />
                          {tViolations(loc.shiftsWithViolations)}
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
  );
}

// ---------------------------------------------------------------------------
// New blocks
// ---------------------------------------------------------------------------

function TemplatesCard({ data }: { data: AnalyticsOverview }): React.JSX.Element {
  const tA = useTranslations("analytics");
  return (
    <Card className="mb-4">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Layers className="size-4 text-primary" />
          {tA("templates.title")}
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-1">
        {data.templates.length === 0 ? (
          <p className="text-sm text-muted-foreground">{tA("templates.empty")}</p>
        ) : (
          <ul className="space-y-2">
            {data.templates.map((t) => {
              const violationsRate =
                t.shiftsTotal > 0
                  ? Math.round((t.shiftsWithViolations / t.shiftsTotal) * 100)
                  : null;
              return (
                <li
                  key={t.templateId}
                  className="flex items-center gap-3 p-2 -mx-2 rounded-md bg-elevated/30"
                >
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{t.templateName}</p>
                    <p className="text-[11px] text-muted-foreground">
                      {tA("templates.shifts", { count: t.shiftsTotal })}
                      {violationsRate !== null && t.shiftsWithViolations > 0 ? (
                        <>
                          {" · "}
                          <span className="text-warning">
                            {tA("templates.violationsRate", { rate: violationsRate })}
                          </span>
                        </>
                      ) : null}
                    </p>
                  </div>
                  <p
                    className={`text-base font-semibold tabular-nums ${scoreColor(t.averageScore)}`}
                  >
                    {formatScore(t.averageScore)}
                  </p>
                </li>
              );
            })}
          </ul>
        )}
        <p className="text-[10px] text-muted-foreground mt-3">{tA("templates.help")}</p>
        <LowDataNote
          flag={data.density?.templates ?? "ok"}
          message={tA("lowData.templates")}
        />
      </CardContent>
    </Card>
  );
}

function CriticalityCard({ data }: { data: AnalyticsOverview }): React.JSX.Element {
  const tA = useTranslations("analytics");
  if (data.criticality.length === 0) return <></>;

  // Order: critical, required, optional. The API sorts alphabetically;
  // we rearrange so the most-important bucket is on top.
  const order: Record<string, number> = { critical: 0, required: 1, optional: 2 };
  const rows = [...data.criticality].sort(
    (a, b) => (order[a.criticality] ?? 99) - (order[b.criticality] ?? 99),
  );

  return (
    <Card className="mb-4">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <ShieldCheck className="size-4 text-primary" />
          {tA("criticality.title")}
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-1 space-y-3">
        {rows.map((row) => {
          const total = Math.max(row.tasksTotal, 1);
          // We pre-compute percentages once: avoids 5 inline divisions in
          // JSX, and keeps the bar widths consistent with the labels.
          const donePct = clampInt((row.done / total) * 100, 0, 100);
          const skippedPct = clampInt((row.skipped / total) * 100, 0, 100);
          const rejectedPct = clampInt(
            (row.waiverRejected / total) * 100,
            0,
            100,
          );
          const labelKey = `criticality.labels.${row.criticality}` as const;
          let label: string;
          try {
            label = tA(labelKey);
          } catch {
            label = row.criticality;
          }
          return (
            <div key={row.criticality}>
              <div className="flex items-baseline justify-between mb-1">
                <p className="text-sm font-medium">{label}</p>
                <p className="text-[11px] text-muted-foreground tabular-nums">
                  {row.tasksTotal}
                </p>
              </div>
              <div className="h-2 w-full overflow-hidden rounded bg-elevated/60 flex">
                <div
                  className="h-full bg-success/70"
                  style={{ width: `${donePct}%` }}
                  title={tA("criticality.done", { count: row.done })}
                />
                <div
                  className="h-full bg-warning/70"
                  style={{ width: `${skippedPct}%` }}
                  title={tA("criticality.skipped", { count: row.skipped })}
                />
                <div
                  className="h-full bg-critical/70"
                  style={{ width: `${rejectedPct}%` }}
                  title={tA("criticality.rejected", { count: row.waiverRejected })}
                />
              </div>
              <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] text-muted-foreground">
                <span className="text-success">
                  {tA("criticality.done", { count: row.done })}
                </span>
                <span className="text-warning">
                  {tA("criticality.skipped", { count: row.skipped })}
                </span>
                <span className="text-critical">
                  {tA("criticality.rejected", { count: row.waiverRejected })}
                </span>
                {row.suspiciousAttachments > 0 ? (
                  <span className="text-warning">
                    {tA("criticality.suspicious", {
                      count: row.suspiciousAttachments,
                    })}
                  </span>
                ) : null}
              </div>
            </div>
          );
        })}
        <p className="text-[10px] text-muted-foreground">{tA("criticality.help")}</p>
      </CardContent>
    </Card>
  );
}

function RoleSplitCard({ data }: { data: AnalyticsOverview }): React.JSX.Element {
  const tA = useTranslations("analytics");
  if (!data.roleSplit) return <></>;
  const { operator, bartender } = data.roleSplit;
  const operatorEmpty = operator.shiftsClosed === 0;
  const bartenderEmpty = bartender.shiftsClosed === 0;
  if (operatorEmpty && bartenderEmpty) return <></>;
  return (
    <Card className="mb-4">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Users className="size-4 text-primary" />
          {tA("roleSplit.title")}
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-1 grid grid-cols-2 gap-3">
        <RoleColumn
          label={tA("roleSplit.operator")}
          kpi={operator}
          emptyLabel={tA("roleSplit.noOperators")}
        />
        <RoleColumn
          label={tA("roleSplit.bartender")}
          kpi={bartender}
          emptyLabel={tA("roleSplit.noBartenders")}
        />
      </CardContent>
    </Card>
  );
}

function RoleColumn({
  label,
  kpi,
  emptyLabel,
}: {
  label: string;
  kpi: AnalyticsKpi;
  emptyLabel: string;
}): React.JSX.Element {
  const empty = kpi.shiftsClosed === 0;
  return (
    <div className="rounded-md border border-border bg-elevated/40 p-3">
      <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
      {empty ? (
        <p className="text-xs text-muted-foreground mt-2">{emptyLabel}</p>
      ) : (
        <div className="mt-2 space-y-1.5">
          <div className="flex items-baseline justify-between">
            <p className="text-[10px] text-muted-foreground">Shifts</p>
            <p className="text-sm tabular-nums">{kpi.shiftsClosed}</p>
          </div>
          <div className="flex items-baseline justify-between">
            <p className="text-[10px] text-muted-foreground">Avg</p>
            <p className={`text-sm tabular-nums ${scoreColor(kpi.averageScore)}`}>
              {formatScore(kpi.averageScore)}
            </p>
          </div>
          <div className="flex items-baseline justify-between">
            <p className="text-[10px] text-muted-foreground">Violations</p>
            <p
              className={`text-sm tabular-nums ${kpi.shiftsWithViolations > 0 ? "text-warning" : "text-foreground"}`}
            >
              {kpi.shiftsWithViolations}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

function SlaCard({ data }: { data: AnalyticsOverview }): React.JSX.Element {
  const tA = useTranslations("analytics");
  const sla = data.slaLateStart;
  if (!sla) return <></>;
  const empty = sla.shiftsWithActual === 0;
  const ratePct = sla.lateRate === null ? null : Math.round(sla.lateRate * 100);
  return (
    <Card className="mb-4">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Timer className="size-4 text-primary" />
          {tA("sla.title")}
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-1">
        {empty ? (
          <p className="text-sm text-muted-foreground">{tA("sla.empty")}</p>
        ) : (
          <div className="space-y-2">
            <div className="flex items-baseline justify-between">
              <p className="text-sm">{tA("sla.lateRate", { rate: ratePct ?? 0 })}</p>
              <p
                className={`text-sm tabular-nums ${(ratePct ?? 0) > 20 ? "text-critical" : (ratePct ?? 0) > 10 ? "text-warning" : "text-success"}`}
              >
                {tA("sla.lateCount", { count: sla.lateCount })}
              </p>
            </div>
            <Progress value={ratePct ?? 0} />
            {sla.avgLateMin !== null ? (
              <p className="text-[11px] text-muted-foreground">
                {tA("sla.avgLate", { value: Math.round(sla.avgLateMin) })}
              </p>
            ) : null}
          </div>
        )}
        <p className="text-[10px] text-muted-foreground mt-3">
          {tA("sla.help", { threshold: sla.thresholdMin })}
        </p>
      </CardContent>
    </Card>
  );
}

function AntifakeCard({ data }: { data: AnalyticsOverview }): React.JSX.Element {
  const tA = useTranslations("analytics");
  const af = data.antifake;
  if (!af) return <></>;
  if (af.attachmentsTotal === 0) {
    return (
      <Card className="mb-4">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Radio className="size-4 text-primary" />
            {tA("antifake.title")}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">{tA("antifake.empty")}</p>
        </CardContent>
      </Card>
    );
  }
  const ratePct = af.suspiciousRate === null ? 0 : Math.round(af.suspiciousRate * 100);
  return (
    <Card className="mb-4">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Radio className="size-4 text-primary" />
          {tA("antifake.title")}
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-1">
        <div className="flex items-baseline justify-between mb-1">
          <p className="text-sm">{tA("antifake.totalAttachments", { count: af.attachmentsTotal })}</p>
          <p
            className={`text-sm tabular-nums ${ratePct > 20 ? "text-critical" : ratePct > 10 ? "text-warning" : "text-success"}`}
          >
            {tA("antifake.rate", { rate: ratePct })}
          </p>
        </div>
        <Progress value={ratePct} />
        <p className="text-[11px] text-muted-foreground mt-2">
          {tA("antifake.suspicious", { count: af.suspiciousTotal })}
        </p>
        <p className="text-[10px] text-muted-foreground mt-3">{tA("antifake.help")}</p>
      </CardContent>
    </Card>
  );
}
