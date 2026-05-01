"use client";

import { ArrowLeft, ScrollText } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  auditBorderClass,
  auditEventIcon,
  auditIconWrapClass,
  normalizeAuditAccent,
} from "@/lib/audit-event-visuals";
import { fetchAuditEvents, type AuditEventRow } from "@/lib/api/audit";
import { actorInitials, APP_TIMEZONE, formatAuditTimestamp } from "@/lib/format-audit-time";
import { localiseApiFailure } from "@/lib/i18n/api-errors";
import { toast } from "@/lib/stores/toast-store";
import { cn } from "@/lib/utils";

interface AuditScreenProps {
  onBack: () => void;
}

export function AuditScreen({ onBack }: AuditScreenProps): React.JSX.Element {
  const t = useTranslations("audit");
  const tErr = useTranslations("errors");
  const locale = useLocale();
  const [items, setItems] = React.useState<AuditEventRow[]>([]);
  const [nextCursor, setNextCursor] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [loadingMore, setLoadingMore] = React.useState(false);

  const formatTime = React.useCallback(
    (iso: string) =>
      formatAuditTimestamp(iso, locale, {
        today: (time) => t("time.today", { time }),
        yesterday: (time) => t("time.yesterday", { time }),
      }),
    [locale, t],
  );

  const loadFirst = React.useCallback(async () => {
    setLoading(true);
    const result = await fetchAuditEvents({ limit: 30 });
    if (result.ok) {
      setItems(result.data.items);
      setNextCursor(result.data.nextCursor);
    } else {
      toast({
        variant: "critical",
        title: tErr("generic"),
        description: localiseApiFailure(result, tErr),
      });
    }
    setLoading(false);
  }, [tErr]);

  const loadMore = React.useCallback(async () => {
    if (!nextCursor || loadingMore) return;
    setLoadingMore(true);
    const result = await fetchAuditEvents({ cursor: nextCursor, limit: 30 });
    setLoadingMore(false);
    if (!result.ok) {
      toast({
        variant: "critical",
        title: tErr("generic"),
        description: localiseApiFailure(result, tErr),
      });
      return;
    }
    setItems((prev) => [...prev, ...result.data.items]);
    setNextCursor(result.data.nextCursor);
  }, [nextCursor, loadingMore, tErr]);

  React.useEffect(() => {
    void loadFirst();
  }, [loadFirst]);

  return (
    <main className="mx-auto max-w-md px-4 pt-4 pb-24 animate-fade-in-up">
      <header className="mb-4 flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={onBack} className="-ml-2 px-2">
          <ArrowLeft className="size-5" />
        </Button>
        <div className="flex-1">
          <h1 className="text-lg font-semibold">{t("title")}</h1>
          <p className="text-xs text-muted-foreground">{t("subtitle")}</p>
          <p className="mt-0.5 text-[10px] text-muted-foreground/80" title={APP_TIMEZONE}>
            {t("timezoneHint", { zone: APP_TIMEZONE })}
          </p>
        </div>
      </header>

      {loading ? (
        <Card className="animate-pulse">
          <CardContent className="h-32 p-6" />
        </Card>
      ) : items.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ScrollText className="size-5 text-muted-foreground" />
              {t("emptyTitle")}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">{t("emptyHint")}</p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {items.map((ev) => {
            const accent = normalizeAuditAccent(ev.accent);
            const Icon = auditEventIcon(ev.eventType, accent);
            const initials = actorInitials(ev.actorName);
            const displayName = ev.actorName?.trim() ? ev.actorName : t("bySystem");

            return (
              <Card
                key={ev.id}
                className={cn("overflow-hidden border-l-4 shadow-sm", auditBorderClass(accent))}
              >
                <CardContent className="p-4">
                  <div className="flex gap-3">
                    <div
                      className={cn(
                        "mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg",
                        auditIconWrapClass(accent),
                      )}
                    >
                      <Icon className="size-4" aria-hidden />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium leading-snug break-words">{ev.message}</p>
                      <div className="mt-3 flex items-center gap-2.5">
                        <div
                          className="flex size-8 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold text-muted-foreground"
                          aria-hidden
                        >
                          {initials}
                        </div>
                        <p className="min-w-0 text-xs text-muted-foreground">
                          <span className="font-medium text-foreground/90">{displayName}</span>
                          <span className="mx-1.5 opacity-60" aria-hidden>
                            ·
                          </span>
                          <time dateTime={ev.createdAt} className="tabular-nums">
                            {formatTime(ev.createdAt)}
                          </time>
                        </p>
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            );
          })}
          <Button
            variant="secondary"
            size="block"
            onClick={() => void loadMore()}
            disabled={!nextCursor || loadingMore}
          >
            {loadingMore ? t("loadingMore") : t("loadMore")}
          </Button>
        </div>
      )}
    </main>
  );
}
