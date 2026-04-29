"use client";

/**
 * Operator profile sheet (S9 drill-down).
 *
 * Opens from the Top violators list and from any future "operator" entry
 * point. We deliberately reuse the existing analytics payload (filtered to
 * one user via the shift history endpoint) instead of adding a new
 * ``/v1/analytics/operator/{id}`` route — at MVP scale the saving from a
 * single round-trip is bigger than the cost of computing rates client-side
 * over the visible page (max 50 rows).
 */

import { ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { fetchHistory, type HistoryItem } from "@/lib/api/shifts";
import type { AnalyticsViolator } from "@/lib/api/analytics";
import { toast } from "@/lib/stores/toast-store";

interface OperatorProfileSheetProps {
  open: boolean;
  operator: AnalyticsViolator | null;
  /** ISO date YYYY-MM-DD, used to scope the operator history. */
  rangeFrom: string | null;
  /** ISO date YYYY-MM-DD. */
  rangeTo: string | null;
  locationId: string | null;
  onOpenChange: (open: boolean) => void;
  onOpenInHistory: () => void;
}

function scoreColor(score: number | null): string {
  if (score === null) return "text-muted-foreground";
  if (score >= 90) return "text-success";
  if (score >= 70) return "text-foreground";
  if (score >= 50) return "text-warning";
  return "text-critical";
}

function formatScore(score: number | null): string {
  if (score === null) return "—";
  return score.toFixed(1);
}

/**
 * Sparkline — same approach as ``history-screen.tsx``: a 60-byte SVG path
 * is dramatically cheaper than dragging in a chart lib, and a sparkline is
 * read for trend shape, not numeric precision.
 */
function Sparkline({
  values,
  width = 160,
  height = 36,
}: {
  values: number[];
  width?: number;
  height?: number;
}): React.JSX.Element | null {
  if (values.length < 2) return null;
  const stepX = width / (values.length - 1);
  const points = values
    .map((v, i) => {
      const clamped = Math.max(0, Math.min(100, v));
      const x = i * stepX;
      const y = height - (clamped / 100) * height;
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

export function OperatorProfileSheet({
  open,
  operator,
  rangeFrom,
  rangeTo,
  locationId,
  onOpenChange,
  onOpenInHistory,
}: OperatorProfileSheetProps): React.JSX.Element {
  const t = useTranslations("operatorSheet");
  const tErr = useTranslations("errors");

  const [items, setItems] = React.useState<HistoryItem[] | null>(null);
  const [loading, setLoading] = React.useState(false);

  const operatorId = operator?.userId ?? null;

  React.useEffect(() => {
    if (!open || !operatorId) {
      setItems(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    void fetchHistory({
      userId: operatorId,
      locationId,
      from: rangeFrom,
      to: rangeTo,
      limit: 50,
    }).then((res) => {
      if (cancelled) return;
      setLoading(false);
      if (res.ok) {
        setItems(res.data.items);
      } else {
        toast({ variant: "critical", title: tErr("generic"), description: t("loadFailed") });
      }
    });
    return () => {
      cancelled = true;
    };
  }, [open, operatorId, rangeFrom, rangeTo, locationId, t, tErr]);

  const violationsRate =
    operator && operator.shiftsTotal > 0
      ? Math.round((operator.shiftsWithViolations / operator.shiftsTotal) * 100)
      : null;

  // The sparkline reads left=oldest -> right=newest (history endpoint
  // returns DESC). We cap to 14 points so the SVG stays legible at sheet
  // width and the cognitive cost of "is it going up?" stays low.
  const trend = React.useMemo(() => {
    if (!items) return [];
    return [...items.slice(0, 14)].reverse().map((it) => it.score ?? 0);
  }, [items]);

  return (
    <Sheet modal={false} open={open} onOpenChange={onOpenChange}>
      <SheetContent title={t("title")}>
        {operator === null ? (
          <p className="text-sm text-muted-foreground">{t("empty")}</p>
        ) : (
          <div>
            <header className="mb-4">
              <p className="text-base font-semibold">{operator.fullName}</p>
              {operator.role ? (
                <p className="text-xs text-muted-foreground capitalize">
                  {/* `role` is one of operator|bartender|admin|owner — fall back to raw value if unmapped */}
                  {(() => {
                    try {
                      return t(`role.${operator.role}` as never);
                    } catch {
                      return operator.role;
                    }
                  })()}
                </p>
              ) : null}
            </header>

            <div className="grid grid-cols-2 gap-2 mb-4">
              <Tile
                label={t("kpiShifts")}
                value={String(operator.shiftsTotal)}
              />
              <Tile
                label={t("kpiAvgScore")}
                value={formatScore(operator.averageScore)}
                valueClassName={scoreColor(operator.averageScore)}
              />
              <Tile
                label={t("kpiViolations")}
                value={String(operator.shiftsWithViolations)}
                hint={
                  violationsRate === null
                    ? null
                    : t("kpiViolationsRate", { rate: violationsRate })
                }
                valueClassName={
                  operator.shiftsWithViolations > 0 ? "text-warning" : "text-foreground"
                }
              />
              <SuspiciousTile items={items} />
            </div>

            {trend.length >= 2 ? (
              <div className="mb-4 rounded-md border border-border bg-elevated/40 px-3 py-2">
                <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
                  {t("trend")}
                </p>
                <div className="mt-1">
                  <Sparkline values={trend} />
                </div>
              </div>
            ) : null}

            {loading && items === null ? (
              <p className="text-sm text-muted-foreground">{t("loading")}</p>
            ) : null}

            <Button
              variant="secondary"
              size="block"
              onClick={() => {
                onOpenChange(false);
                onOpenInHistory();
              }}
            >
              {t("openInHistory")}
              <ChevronRight className="size-4" />
            </Button>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}

function Tile({
  label,
  value,
  hint,
  valueClassName,
}: {
  label: string;
  value: string;
  hint?: string | null;
  valueClassName?: string;
}): React.JSX.Element {
  return (
    <div className="rounded-md border border-border bg-elevated/40 px-3 py-2">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={`text-lg font-semibold tabular-nums mt-0.5 ${valueClassName ?? ""}`}>
        {value}
      </p>
      {hint ? <p className="text-[10px] text-muted-foreground mt-0.5">{hint}</p> : null}
    </div>
  );
}

function SuspiciousTile({ items }: { items: HistoryItem[] | null }): React.JSX.Element {
  const t = useTranslations("operatorSheet");
  // Photo-quality breakdown is a [0, 1] ratio of "non-suspicious / total".
  // We invert to surface "% suspicious", since that's the lever owners
  // care about. Skip rows where the ratio is null (no photos uploaded).
  const ratios =
    items?.flatMap((it) =>
      it.breakdown && it.breakdown.photoQuality !== null
        ? [1 - it.breakdown.photoQuality]
        : [],
    ) ?? [];
  const avgSuspicious =
    ratios.length === 0
      ? null
      : Math.round((ratios.reduce((s, r) => s + r, 0) / ratios.length) * 100);
  return (
    <div className="rounded-md border border-border bg-elevated/40 px-3 py-2">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {t("kpiSuspicious", { rate: avgSuspicious ?? 0 })}
      </p>
      <p className="text-lg font-semibold tabular-nums mt-0.5">
        {avgSuspicious === null ? "—" : `${avgSuspicious}%`}
      </p>
    </div>
  );
}
