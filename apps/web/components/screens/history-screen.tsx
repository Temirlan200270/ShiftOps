"use client";

import {
  ArrowLeft,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  ShieldAlert,
  TrendingUp,
  X,
} from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { fetchHistory, type HistoryItem, type HistoryPage } from "@/lib/api/shifts";
import { localiseApiFailure } from "@/lib/i18n/api-errors";
import { toast } from "@/lib/stores/toast-store";
import { SCORE_WEIGHTS, type ScoreBreakdown } from "@/lib/types";

export interface HistoryFilters {
  userId?: string | null;
  userName?: string | null;
  locationId?: string | null;
  locationName?: string | null;
  /** ISO date YYYY-MM-DD. */
  from?: string | null;
  /** ISO date YYYY-MM-DD. */
  to?: string | null;
  slotIndex?: number | null;
  stationLabel?: string | null;
  /** Only shifts with NULL station_label (e.g. drill-down from analytics). */
  stationLabelEmpty?: boolean;
}

interface HistoryScreenProps {
  onBack: () => void;
  filters?: HistoryFilters;
  /** Called when the user clears the filter chips at the top. */
  onClearFilters?: () => void;
}

/**
 * Mini sparkline of recent scores. We render with SVG (no chart library) —
 * 8 KB shipped per chart-lib install would dwarf the 60-byte SVG path here,
 * and a sparkline is read for shape, not values, so we don't need axes.
 */
function Sparkline({
  values,
  width = 88,
  height = 28,
}: {
  values: number[];
  width?: number;
  height?: number;
}): React.JSX.Element | null {
  if (values.length < 2) return null;
  const max = 100;
  const min = 0;
  const stepX = width / (values.length - 1);
  const points = values
    .map((v, i) => {
      const x = i * stepX;
      const yRatio = (v - min) / (max - min);
      const y = height - yRatio * height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="text-primary"
      aria-hidden
    >
      <polyline
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        points={points}
      />
    </svg>
  );
}

function formatScore(score: number | null): string {
  if (score === null) return "—";
  return score.toFixed(1);
}

function scoreColor(score: number | null): string {
  if (score === null) return "text-muted-foreground";
  if (score >= 90) return "text-success";
  if (score >= 70) return "text-foreground";
  if (score >= 50) return "text-warning";
  return "text-critical";
}

function HistoryRow({
  item,
  expanded,
  onToggle,
  onOpenHandover,
}: {
  item: HistoryItem;
  expanded: boolean;
  onToggle: () => void;
  onOpenHandover: () => void;
}): React.JSX.Element {
  const tHist = useTranslations("history");
  const tSum = useTranslations("summary");
  const tDash = useTranslations("dashboard");

  return (
    <Card
      className="mb-2"
      accent={item.status === "closed_with_violations" ? "warning" : "none"}
    >
      <button
        type="button"
        onClick={onToggle}
        className="w-full text-left"
        aria-expanded={expanded}
      >
        <CardContent className="p-4 flex items-center gap-3">
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium truncate">{item.templateName}</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              {new Date(item.scheduledStart).toLocaleDateString()} ·{" "}
              {tDash(`shiftStatus.${item.status}`)}
            </p>
            <p className="text-[11px] text-muted-foreground mt-0.5">
              {item.stationLabel
                ? tHist("postMeta", { label: item.stationLabel, index: item.slotIndex })
                : tHist("postMetaNoLabel", { index: item.slotIndex })}
            </p>
            {item.delayReason ? (
              <p className="text-[11px] text-warning mt-0.5 line-clamp-2">
                {tHist("delayReason", { reason: item.delayReason })}
              </p>
            ) : null}
          </div>
          <div className="text-right shrink-0">
            <p className={`text-lg font-semibold tabular-nums ${scoreColor(item.score)}`}>
              {formatScore(item.score)}
            </p>
            <p className="text-[10px] text-muted-foreground">
              {tHist("tasksDone", { done: item.tasksDone, total: item.tasksTotal })}
            </p>
          </div>
          {expanded ? (
            <ChevronDown className="size-4 text-muted-foreground shrink-0" />
          ) : (
            <ChevronRight className="size-4 text-muted-foreground shrink-0" />
          )}
        </CardContent>
      </button>
      {expanded && (item.breakdown || item.handoverSummary) ? (
        <CardContent className="px-4 pb-4 pt-0 border-t border-border/60">
          {item.handoverSummary ? (
            <div className="mt-3">
              <Button variant="secondary" size="sm" onClick={onOpenHandover}>
                {tHist("handoverCta")}
              </Button>
            </div>
          ) : null}
          {item.breakdown ? (
            <ul className="space-y-2 mt-3">
              {(Object.keys(SCORE_WEIGHTS) as Array<keyof ScoreBreakdown>).map((key) => {
                const ratio = item.breakdown![key];
                const points = Math.round(ratio * SCORE_WEIGHTS[key] * 100) / 100;
                return (
                  <li key={key}>
                    <div className="flex items-baseline justify-between gap-2 text-xs">
                      <span className="text-muted-foreground">
                        {tSum(`components.${key}`)}
                      </span>
                      <span className="tabular-nums">
                        {points.toFixed(1)} / {SCORE_WEIGHTS[key]}
                      </span>
                    </div>
                    <Progress value={ratio * 100} className="h-1 mt-1" />
                  </li>
                );
              })}
            </ul>
          ) : null}
        </CardContent>
      ) : null}
    </Card>
  );
}

export function HistoryScreen({
  onBack,
  filters,
  onClearFilters,
}: HistoryScreenProps): React.JSX.Element {
  const tHist = useTranslations("history");
  const tErr = useTranslations("errors");

  const [page, setPage] = React.useState<HistoryPage | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [loadingMore, setLoadingMore] = React.useState(false);
  const [expandedId, setExpandedId] = React.useState<string | null>(null);
  const [handoverOpen, setHandoverOpen] = React.useState(false);
  const [handoverText, setHandoverText] = React.useState<string | null>(null);

  const [slotFilterDraft, setSlotFilterDraft] = React.useState("");
  const [stationFilterDraft, setStationFilterDraft] = React.useState("");
  const [postSlotIndex, setPostSlotIndex] = React.useState<number | null>(null);
  const [postStationLabel, setPostStationLabel] = React.useState<string | null>(null);
  const [postStationLabelEmpty, setPostStationLabelEmpty] = React.useState(false);

  // Snapshot the filter values into stable primitives so the effect
  // dependency array doesn't re-run on every parent render (an inline
  // object identity changes each time even when the values don't).
  const filterUserId = filters?.userId ?? null;
  const filterLocationId = filters?.locationId ?? null;
  const filterFrom = filters?.from ?? null;
  const filterTo = filters?.to ?? null;
  const postFilterActive =
    postSlotIndex !== null || postStationLabel !== null || postStationLabelEmpty;
  const filtersActive = Boolean(
    filterUserId ?? filterLocationId ?? filterFrom ?? filterTo ?? postFilterActive,
  );

  const applyPostFilter = React.useCallback(() => {
    const raw = slotFilterDraft.trim();
    let slot: number | null = null;
    if (raw !== "") {
      const n = parseInt(raw, 10);
      if (Number.isNaN(n) || n < 0) {
        toast({ variant: "critical", title: tHist("invalidSlotNumber") });
        return;
      }
      slot = n;
    }
    const st = stationFilterDraft.trim();
    setPostSlotIndex(slot);
    setPostStationLabel(st === "" ? null : st);
    setPostStationLabelEmpty(false);
  }, [slotFilterDraft, stationFilterDraft, tHist]);

  const clearPostFilter = React.useCallback(() => {
    setSlotFilterDraft("");
    setStationFilterDraft("");
    setPostSlotIndex(null);
    setPostStationLabel(null);
    setPostStationLabelEmpty(false);
  }, []);

  React.useEffect(() => {
    if (!filters) return;
    const hasPostNav =
      filters.slotIndex != null ||
      filters.stationLabel !== undefined ||
      filters.stationLabelEmpty === true;
    if (!hasPostNav) return;
    if (filters.slotIndex != null) {
      setPostSlotIndex(filters.slotIndex);
      setSlotFilterDraft(String(filters.slotIndex));
    }
    if (filters.stationLabelEmpty) {
      setPostStationLabelEmpty(true);
      setPostStationLabel(null);
      setStationFilterDraft("");
    } else {
      setPostStationLabelEmpty(false);
      if (filters.stationLabel !== undefined) {
        setPostStationLabel(filters.stationLabel);
        setStationFilterDraft(filters.stationLabel ?? "");
      }
    }
  }, [filters]);

  const loadFirstPage = React.useCallback(async () => {
    setLoading(true);
    const result = await fetchHistory({
      userId: filterUserId,
      locationId: filterLocationId,
      from: filterFrom,
      to: filterTo,
      slotIndex: postSlotIndex ?? undefined,
      stationLabel: postStationLabel ?? undefined,
      stationLabelEmpty: postStationLabelEmpty ? true : undefined,
    });
    if (result.ok) {
      setPage(result.data);
    } else {
      toast({
        variant: "critical",
        title: tErr("generic"),
        description: localiseApiFailure(result, tErr),
      });
    }
    setLoading(false);
  }, [
    tErr,
    filterUserId,
    filterLocationId,
    filterFrom,
    filterTo,
    postSlotIndex,
    postStationLabel,
    postStationLabelEmpty,
  ]);

  const loadMore = React.useCallback(async () => {
    if (!page?.nextCursor || loadingMore) return;
    setLoadingMore(true);
    const result = await fetchHistory({
      cursor: page.nextCursor,
      userId: filterUserId,
      locationId: filterLocationId,
      from: filterFrom,
      to: filterTo,
      slotIndex: postSlotIndex ?? undefined,
      stationLabel: postStationLabel ?? undefined,
      stationLabelEmpty: postStationLabelEmpty ? true : undefined,
    });
    setLoadingMore(false);
    if (!result.ok) {
      toast({
        variant: "critical",
        title: tErr("generic"),
        description: localiseApiFailure(result, tErr),
      });
      return;
    }
    setPage({
      items: [...page.items, ...result.data.items],
      nextCursor: result.data.nextCursor,
    });
  }, [
    page,
    loadingMore,
    tErr,
    filterUserId,
    filterLocationId,
    filterFrom,
    filterTo,
    postSlotIndex,
    postStationLabel,
    postStationLabelEmpty,
  ]);

  React.useEffect(() => {
    void loadFirstPage();
  }, [loadFirstPage]);

  const items = page?.items ?? [];
  const handleOpenHandover = React.useCallback((item: HistoryItem) => {
    setHandoverText(item.handoverSummary ?? null);
    setHandoverOpen(true);
  }, []);
  const recent7 = React.useMemo(
    // History comes back DESC, so the newest is index 0. Reverse so the
    // sparkline reads left=oldest -> right=newest, matching every other
    // chart in the world. Depend on `page` rather than the derived
    // `items` array (its identity changes every render).
    () => [...(page?.items ?? []).slice(0, 7)].reverse().map((it) => it.score ?? 0),
    [page],
  );
  const average =
    items.length === 0
      ? null
      : items.reduce((sum, it) => sum + (it.score ?? 0), 0) / items.length;

  return (
    <main className="mx-auto max-w-md px-4 pt-4 pb-24 animate-fade-in-up">
      <header className="flex items-center gap-3 mb-4">
        <Button variant="ghost" size="sm" onClick={onBack} className="-ml-2 px-2">
          <ArrowLeft className="size-5" />
        </Button>
        <div className="flex-1">
          <h1 className="text-lg font-semibold">{tHist("title")}</h1>
          <p className="text-xs text-muted-foreground">
            {filtersActive
              ? tHist("subtitleFiltered", { count: items.length })
              : tHist("subtitle", { count: items.length })}
          </p>
        </div>
      </header>

      <div className="mb-4 rounded-lg border border-border/60 bg-elevated/30 p-3 space-y-2">
        <p className="text-xs font-medium text-muted-foreground">{tHist("filterPostSlot")}</p>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <input
            type="text"
            inputMode="numeric"
            className="w-full sm:flex-1 rounded-md border border-border bg-background px-2.5 py-1.5 text-sm"
            placeholder={tHist("filterSlotIndex")}
            value={slotFilterDraft}
            onChange={(e) => setSlotFilterDraft(e.target.value)}
          />
          <input
            type="text"
            className="w-full sm:flex-1 rounded-md border border-border bg-background px-2.5 py-1.5 text-sm"
            placeholder={tHist("filterStationLabel")}
            value={stationFilterDraft}
            onChange={(e) => setStationFilterDraft(e.target.value)}
          />
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="button" size="sm" variant="secondary" onClick={() => void applyPostFilter()}>
            {tHist("applyPostFilter")}
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={clearPostFilter}>
            {tHist("clearPostFilter")}
          </Button>
        </div>
      </div>

      <Sheet open={handoverOpen} onOpenChange={setHandoverOpen}>
        <SheetTrigger asChild>
          <span hidden />
        </SheetTrigger>
        <SheetContent title={tHist("handoverTitle")}>
          <pre className="text-xs whitespace-pre-wrap break-words bg-elevated/60 border border-border rounded-md p-3">
            {handoverText ?? ""}
          </pre>
        </SheetContent>
      </Sheet>

      {filtersActive ? (
        <div className="mb-4 flex flex-wrap items-center gap-2">
          {filters?.userName ? (
            <FilterChip label={tHist("filterUserChip", { name: filters.userName })} />
          ) : null}
          {filters?.locationName ? (
            <FilterChip label={tHist("filterLocationChip", { name: filters.locationName })} />
          ) : null}
          {filterFrom && filterTo ? (
            <FilterChip
              label={tHist("filterDateChip", { from: filterFrom, to: filterTo })}
            />
          ) : null}
          {postSlotIndex !== null ? (
            <FilterChip label={tHist("filterPostChipSlot", { index: postSlotIndex })} />
          ) : null}
          {postStationLabelEmpty ? (
            <FilterChip label={tHist("filterPostChipNoLabel")} />
          ) : null}
          {postStationLabel ? (
            <FilterChip label={tHist("filterPostChipStation", { name: postStationLabel })} />
          ) : null}
          {onClearFilters ? (
            <button
              type="button"
              onClick={onClearFilters}
              className="inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground"
            >
              <X className="size-3" />
              {tHist("clearFilters")}
            </button>
          ) : null}
        </div>
      ) : null}

      {loading ? (
        <Card className="animate-pulse">
          <CardContent className="p-6 h-32" />
        </Card>
      ) : items.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <CalendarDays className="size-5 text-muted-foreground" />
              {filtersActive ? tHist("emptyFiltered") : tHist("empty")}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">{tHist("emptyHint")}</p>
          </CardContent>
        </Card>
      ) : (
        <>
          <Card className="mb-3">
            <CardContent className="p-4 flex items-center gap-4">
              <div className="flex-1">
                <p className="text-xs text-muted-foreground flex items-center gap-1">
                  <TrendingUp className="size-3.5" />
                  {tHist("trend7d")}
                </p>
                <p className={`text-2xl font-semibold mt-1 ${scoreColor(average)}`}>
                  {average === null ? "—" : average.toFixed(1)}
                </p>
                <p className="text-[10px] text-muted-foreground">
                  {tHist("averageScore")}
                </p>
              </div>
              <Sparkline values={recent7} />
            </CardContent>
          </Card>

          {items.map((item) => (
            <HistoryRow
              key={item.id}
              item={item}
              expanded={expandedId === item.id}
              onToggle={() => setExpandedId(expandedId === item.id ? null : item.id)}
              onOpenHandover={() => handleOpenHandover(item)}
            />
          ))}

          {page?.nextCursor ? (
            <Button
              variant="secondary"
              size="block"
              onClick={() => void loadMore()}
              disabled={loadingMore}
              className="mt-4"
            >
              {loadingMore ? tHist("loading") : tHist("loadMore")}
            </Button>
          ) : null}

          <div className="mt-6 flex items-center justify-center gap-4 text-[10px] text-muted-foreground">
            <span className="flex items-center gap-1">
              <CheckCircle2 className="size-3 text-success" />
              ≥ 90
            </span>
            <span className="flex items-center gap-1">
              <ShieldAlert className="size-3 text-warning" />
              50–89
            </span>
            <span className="flex items-center gap-1">
              <ShieldAlert className="size-3 text-critical" />
              &lt; 50
            </span>
          </div>
        </>
      )}
    </main>
  );
}

function FilterChip({ label }: { label: string }): React.JSX.Element {
  return (
    <span className="inline-flex items-center rounded-full border border-border bg-elevated/60 px-2.5 py-1 text-[11px] text-foreground">
      {label}
    </span>
  );
}
