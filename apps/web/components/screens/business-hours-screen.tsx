"use client";

import { ArrowLeft, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  fetchBusinessHours,
  saveBusinessHours,
  type BusinessHoursDTO,
  type DatedHoursRowDTO,
  type RegularHoursRowDTO,
} from "@/lib/api/organization";
import { toast } from "@/lib/stores/toast-store";
import { haptic } from "@/lib/telegram/init";

const ISO_WEEKDAYS: ReadonlyArray<number> = [1, 2, 3, 4, 5, 6, 7];

interface BusinessHoursScreenProps {
  onBack: () => void;
}

type LocalRegular = RegularHoursRowDTO & { localKey: string };
type LocalDated = DatedHoursRowDTO & { localKey: string };

function newKey(): string {
  return crypto.randomUUID();
}

function mapFromDto(dto: BusinessHoursDTO): { tz: string; regular: LocalRegular[]; dated: LocalDated[] } {
  return {
    tz: dto.timezone ?? "",
    regular: dto.regular.map((r) => ({
      localKey: newKey(),
      weekdays: [...r.weekdays].sort((a, b) => a - b),
      opens: r.opens,
      closes: r.closes,
    })),
    dated: dto.dated.map((d) => ({
      localKey: newKey(),
      on: d.on,
      opens: d.opens,
      closes: d.closes,
      note: d.note ?? "",
    })),
  };
}

function toDto(tz: string, regular: LocalRegular[], dated: LocalDated[]): BusinessHoursDTO {
  return {
    timezone: tz.trim() === "" ? null : tz.trim(),
    regular: regular.map(({ weekdays, opens, closes }) => ({ weekdays, opens, closes })),
    dated: dated.map(({ on, opens, closes, note }) => {
      const n = (note ?? "").trim();
      return {
        on,
        opens,
        closes,
        note: n === "" ? null : n,
      };
    }),
  };
}

export function BusinessHoursScreen({ onBack }: BusinessHoursScreenProps): React.JSX.Element {
  const t = useTranslations("orgBusinessHours");
  const tErr = useTranslations("errors");

  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [tz, setTz] = React.useState("");
  const [regular, setRegular] = React.useState<LocalRegular[]>([]);
  const [dated, setDated] = React.useState<LocalDated[]>([]);

  React.useEffect(() => {
    void (async () => {
      setLoading(true);
      const r = await fetchBusinessHours();
      setLoading(false);
      if (!r.ok) {
        toast({ variant: "critical", title: tErr("generic"), description: r.message });
        return;
      }
      const m = mapFromDto(r.data);
      setTz(m.tz);
      setRegular(m.regular);
      setDated(m.dated);
    })();
  }, [tErr]);

  const addRegular = (): void => {
    haptic("light");
    setRegular((prev) => [
      ...prev,
      {
        localKey: newKey(),
        weekdays: [1, 2, 3, 4, 5, 6, 7],
        opens: "09:00",
        closes: "23:00",
      },
    ]);
  };

  const removeRegular = (key: string): void => {
    haptic("light");
    setRegular((prev) => prev.filter((x) => x.localKey !== key));
  };

  const patchRegular = (key: string, patch: Partial<Omit<LocalRegular, "localKey">>): void => {
    setRegular((prev) =>
      prev.map((row) => (row.localKey === key ? { ...row, ...patch } : row)),
    );
  };

  const toggleWeekday = (rowKey: string, d: number): void => {
    setRegular((prev) =>
      prev.map((row) => {
        if (row.localKey !== rowKey) return row;
        const has = row.weekdays.includes(d);
        const next = has ? row.weekdays.filter((x) => x !== d) : [...row.weekdays, d].sort((a, b) => a - b);
        return { ...row, weekdays: next.length === 0 ? [d] : next };
      }),
    );
  };

  const addDated = (): void => {
    haptic("light");
    const today = new Date().toISOString().slice(0, 10);
    setDated((prev) => [
      ...prev,
      { localKey: newKey(), on: today, opens: "10:00", closes: "22:00", note: "" },
    ]);
  };

  const removeDated = (key: string): void => {
    haptic("light");
    setDated((prev) => prev.filter((x) => x.localKey !== key));
  };

  const patchDated = (key: string, patch: Partial<Omit<LocalDated, "localKey">>): void => {
    setDated((prev) => prev.map((row) => (row.localKey === key ? { ...row, ...patch } : row)));
  };

  const handleSave = async (): Promise<void> => {
    haptic("medium");
    setSaving(true);
    const body = toDto(tz, regular, dated);
    const r = await saveBusinessHours(body);
    setSaving(false);
    if (!r.ok) {
      toast({ variant: "critical", title: tErr("generic"), description: r.message });
      return;
    }
    const m = mapFromDto(r.data);
    setTz(m.tz);
    setRegular(m.regular);
    setDated(m.dated);
    toast({ variant: "success", title: t("saved"), duration: 2500 });
  };

  return (
    <main className="mx-auto max-w-md px-4 pt-4 pb-24 animate-fade-in-up">
      <header className="flex items-center gap-3 mb-4">
        <Button variant="ghost" size="sm" onClick={onBack} className="-ml-2 px-2" type="button">
          <ArrowLeft className="size-5" />
        </Button>
        <div className="flex-1 min-w-0">
          <h1 className="text-lg font-semibold">{t("title")}</h1>
          <p className="text-xs text-muted-foreground mt-0.5">{t("subtitle")}</p>
        </div>
      </header>

      {loading ? (
        <Card>
          <CardContent className="p-6 animate-pulse h-32" />
        </Card>
      ) : (
        <>
          <Card className="mb-4">
            <CardHeader>
              <CardTitle className="text-base">{t("timezoneTitle")}</CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              <input
                type="text"
                value={tz}
                onChange={(e) => {
                  setTz(e.target.value);
                }}
                placeholder={t("timezonePlaceholder")}
                className="w-full rounded-md bg-elevated p-2 text-sm border border-border focus:outline-none focus:ring-2 focus:ring-ring"
              />
              <p className="text-[11px] text-muted-foreground mt-2">{t("timezoneHint")}</p>
            </CardContent>
          </Card>

          <Card className="mb-4">
            <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0">
              <CardTitle className="text-base">{t("regularTitle")}</CardTitle>
              <Button variant="secondary" size="sm" type="button" onClick={addRegular}>
                <Plus className="size-4" />
                {t("addRegular")}
              </Button>
            </CardHeader>
            <CardContent className="space-y-4 pt-0">
              {regular.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t("regularEmpty")}</p>
              ) : (
                regular.map((row) => (
                  <div
                    key={row.localKey}
                    className="rounded-lg border border-border/80 p-3 space-y-3 bg-elevated/40"
                  >
                    <div className="flex justify-between items-center">
                      <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                        {t("regularRowLabel")}
                      </span>
                      <button
                        type="button"
                        onClick={() => {
                          removeRegular(row.localKey);
                        }}
                        className="p-1.5 rounded-md text-muted-foreground hover:bg-critical/10 hover:text-critical"
                        aria-label={t("removeRow")}
                      >
                        <Trash2 className="size-4" />
                      </button>
                    </div>
                    <div>
                      <span className="text-xs text-muted-foreground">{t("weekdaysLabel")}</span>
                      <div className="mt-1 flex gap-1 flex-wrap">
                        {ISO_WEEKDAYS.map((d) => {
                          const active = row.weekdays.includes(d);
                          return (
                            <button
                              key={d}
                              type="button"
                              onClick={() => {
                                toggleWeekday(row.localKey, d);
                              }}
                              aria-pressed={active}
                              className={[
                                "px-2.5 py-1 rounded-full text-xs border transition-colors",
                                active
                                  ? "bg-primary/10 border-primary/40 text-primary"
                                  : "bg-elevated border-border text-muted-foreground",
                              ].join(" ")}
                            >
                              {t(`weekday.${d}`)}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <label className="block">
                        <span className="text-xs text-muted-foreground">{t("opens")}</span>
                        <input
                          type="time"
                          value={row.opens}
                          onChange={(e) => {
                            patchRegular(row.localKey, { opens: e.target.value });
                          }}
                          className="mt-1 w-full rounded-md bg-elevated p-2 text-sm border border-border"
                        />
                      </label>
                      <label className="block">
                        <span className="text-xs text-muted-foreground">{t("closes")}</span>
                        <input
                          type="time"
                          value={row.closes}
                          onChange={(e) => {
                            patchRegular(row.localKey, { closes: e.target.value });
                          }}
                          className="mt-1 w-full rounded-md bg-elevated p-2 text-sm border border-border"
                        />
                      </label>
                    </div>
                  </div>
                ))
              )}
            </CardContent>
          </Card>

          <Card className="mb-6">
            <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0">
              <CardTitle className="text-base">{t("datedTitle")}</CardTitle>
              <Button variant="secondary" size="sm" type="button" onClick={addDated}>
                <Plus className="size-4" />
                {t("addDated")}
              </Button>
            </CardHeader>
            <CardContent className="space-y-4 pt-0">
              {dated.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t("datedEmpty")}</p>
              ) : (
                dated.map((row) => (
                  <div
                    key={row.localKey}
                    className="rounded-lg border border-border/80 p-3 space-y-3 bg-elevated/40"
                  >
                    <div className="flex justify-between items-center">
                      <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                        {t("datedRowLabel")}
                      </span>
                      <button
                        type="button"
                        onClick={() => {
                          removeDated(row.localKey);
                        }}
                        className="p-1.5 rounded-md text-muted-foreground hover:bg-critical/10 hover:text-critical"
                        aria-label={t("removeRow")}
                      >
                        <Trash2 className="size-4" />
                      </button>
                    </div>
                    <label className="block">
                      <span className="text-xs text-muted-foreground">{t("dateLabel")}</span>
                      <input
                        type="date"
                        value={row.on}
                        onChange={(e) => {
                          patchDated(row.localKey, { on: e.target.value });
                        }}
                        className="mt-1 w-full rounded-md bg-elevated p-2 text-sm border border-border"
                      />
                    </label>
                    <div className="grid grid-cols-2 gap-2">
                      <label className="block">
                        <span className="text-xs text-muted-foreground">{t("opens")}</span>
                        <input
                          type="time"
                          value={row.opens}
                          onChange={(e) => {
                            patchDated(row.localKey, { opens: e.target.value });
                          }}
                          className="mt-1 w-full rounded-md bg-elevated p-2 text-sm border border-border"
                        />
                      </label>
                      <label className="block">
                        <span className="text-xs text-muted-foreground">{t("closes")}</span>
                        <input
                          type="time"
                          value={row.closes}
                          onChange={(e) => {
                            patchDated(row.localKey, { closes: e.target.value });
                          }}
                          className="mt-1 w-full rounded-md bg-elevated p-2 text-sm border border-border"
                        />
                      </label>
                    </div>
                    <label className="block">
                      <span className="text-xs text-muted-foreground">{t("noteLabel")}</span>
                      <input
                        type="text"
                        value={row.note ?? ""}
                        onChange={(e) => {
                          patchDated(row.localKey, { note: e.target.value });
                        }}
                        placeholder={t("notePlaceholder")}
                        className="mt-1 w-full rounded-md bg-elevated p-2 text-sm border border-border"
                      />
                    </label>
                  </div>
                ))
              )}
            </CardContent>
          </Card>

          <Button size="block" type="button" onClick={() => void handleSave()} disabled={saving}>
            {saving ? t("saving") : t("save")}
          </Button>
        </>
      )}
    </main>
  );
}
