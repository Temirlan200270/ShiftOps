"use client";

import { ArrowLeft, ScrollText } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { fetchAuditEvents, type AuditEventRow } from "@/lib/api/audit";
import { localiseApiFailure } from "@/lib/i18n/api-errors";
import { toast } from "@/lib/stores/toast-store";

interface AuditScreenProps {
  onBack: () => void;
}

function formatTs(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleString();
}

export function AuditScreen({ onBack }: AuditScreenProps): React.JSX.Element {
  const t = useTranslations("audit");
  const tErr = useTranslations("errors");
  const [items, setItems] = React.useState<AuditEventRow[]>([]);
  const [nextCursor, setNextCursor] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [loadingMore, setLoadingMore] = React.useState(false);

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
      <header className="flex items-center gap-3 mb-4">
        <Button variant="ghost" size="sm" onClick={onBack} className="-ml-2 px-2">
          <ArrowLeft className="size-5" />
        </Button>
        <div className="flex-1">
          <h1 className="text-lg font-semibold">{t("title")}</h1>
          <p className="text-xs text-muted-foreground">{t("subtitle")}</p>
        </div>
      </header>

      {loading ? (
        <Card className="animate-pulse">
          <CardContent className="p-6 h-32" />
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
          {items.map((ev) => (
            <Card key={ev.id}>
              <CardContent className="p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-medium break-words">{ev.message}</p>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {ev.actorName ? t("by", { name: ev.actorName }) : t("bySystem")} ·{" "}
                      {formatTs(ev.createdAt)}
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
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

