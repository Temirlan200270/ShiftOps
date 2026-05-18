"use client";

import { ArrowLeft, BadgeInfo, Bell, Fingerprint, Languages, LogOut, User } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  fetchNotificationPrefs,
  saveNotificationPrefs,
  type NotificationPrefsDTO,
} from "@/lib/api/organization";
import { toast } from "@/lib/stores/toast-store";
import { isShiftCloseBiometricSupported } from "@/lib/telegram/biometric";
import { usePreferencesStore } from "@/lib/stores/preferences-store";
import { useAuthStore } from "@/lib/stores/auth-store";
import type { SupportedLocale } from "@/i18n";

function setLocaleCookie(locale: SupportedLocale): void {
  document.cookie = `NEXT_LOCALE=${locale}; path=/; max-age=31536000; SameSite=Lax`;
}

interface SettingsScreenProps {
  onBack: () => void;
}

const ROLE_LABELS: Record<string, string> = {
  owner: "Владелец",
  admin: "Администратор",
  operator: "Оператор",
  bartender: "Бармен",
};

const DEFAULT_NOTIF_PREFS: NotificationPrefsDTO = {
  checklist_overdue: { enabled: true, delay_min: 60, repeat_min: 5, max_alerts: 12 },
};

function NotificationPrefsCard(): React.JSX.Element {
  const t = useTranslations("settings");
  const [prefs, setPrefs] = React.useState<NotificationPrefsDTO>(DEFAULT_NOTIF_PREFS);
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [savedOk, setSavedOk] = React.useState(false);

  React.useEffect(() => {
    fetchNotificationPrefs().then((res) => {
      if (res.ok) setPrefs(res.data);
      else toast({ variant: "critical", title: t("notifications.loadError") });
      setLoading(false);
    });
  }, [t]);

  const patch = (next: Partial<NotificationPrefsDTO["checklist_overdue"]>): void => {
    setSavedOk(false);
    setPrefs((p) => ({ ...p, checklist_overdue: { ...p.checklist_overdue, ...next } }));
  };

  const handleSave = async (): Promise<void> => {
    setSaving(true);
    setSavedOk(false);
    const res = await saveNotificationPrefs(prefs);
    setSaving(false);
    if (res.ok) {
      setSavedOk(true);
    } else {
      toast({ variant: "critical", title: t("notifications.saveError"), description: res.message });
    }
  };

  const co = prefs.checklist_overdue;

  return (
    <Card className="mb-3">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Bell className="size-5 text-muted-foreground" />
          {t("notifications.title")}
          <span className="ml-auto text-[10px] font-normal text-muted-foreground uppercase tracking-wide">
            {t("notifications.ownerOnly")}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <p className="text-sm font-medium mb-1">{t("notifications.checklistOverdue")}</p>
          <p className="text-xs text-muted-foreground mb-3">{t("notifications.checklistOverdueBody")}</p>

          <label className="flex cursor-pointer items-center justify-between gap-4 rounded-lg border border-border bg-elevated/40 px-3 py-3 mb-3">
            <span className="text-sm font-medium">{t("notifications.enabled")}</span>
            <input
              type="checkbox"
              className="size-5 accent-primary"
              checked={co.enabled}
              disabled={loading}
              onChange={(e) => patch({ enabled: e.target.checked })}
            />
          </label>

          {co.enabled && (
            <div className="space-y-3">
              <NumberField
                label={t("notifications.delayMin")}
                unit={t("notifications.delayMinUnit")}
                value={co.delay_min}
                min={10}
                max={480}
                disabled={loading}
                onChange={(v) => patch({ delay_min: v })}
              />
              <NumberField
                label={t("notifications.repeatMin")}
                unit={t("notifications.repeatMinUnit")}
                value={co.repeat_min}
                min={1}
                max={60}
                disabled={loading}
                onChange={(v) => patch({ repeat_min: v })}
              />
              <NumberField
                label={t("notifications.maxAlerts")}
                unit=""
                value={co.max_alerts}
                min={1}
                max={48}
                disabled={loading}
                onChange={(v) => patch({ max_alerts: v })}
              />
            </div>
          )}
        </div>

        <Button
          size="block"
          variant={savedOk ? "secondary" : "primary"}
          disabled={saving || loading}
          onClick={() => void handleSave()}
        >
          {saving
            ? t("notifications.saving")
            : savedOk
              ? t("notifications.saved")
              : t("notifications.save")}
        </Button>
      </CardContent>
    </Card>
  );
}

function NumberField({
  label,
  unit,
  value,
  min,
  max,
  disabled,
  onChange,
}: {
  label: string;
  unit: string;
  value: number;
  min: number;
  max: number;
  disabled: boolean;
  onChange: (v: number) => void;
}): React.JSX.Element {
  const clamp = (v: number): number => Math.max(min, Math.min(max, v));
  return (
    <div className="flex items-center justify-between rounded-lg border border-border bg-elevated/40 px-3 py-2.5 gap-3">
      <span className="text-sm text-muted-foreground flex-1">{label}</span>
      <div className="flex items-center gap-1">
        <button
          type="button"
          disabled={disabled || value <= min}
          onClick={() => onChange(clamp(value - 1))}
          className="size-7 flex items-center justify-center rounded-md border border-border text-muted-foreground active:bg-elevated disabled:opacity-30"
        >
          –
        </button>
        <input
          type="number"
          min={min}
          max={max}
          value={value}
          disabled={disabled}
          onChange={(e) => {
            const n = parseInt(e.target.value, 10);
            if (!isNaN(n)) onChange(clamp(n));
          }}
          className="w-14 text-center text-sm font-medium bg-transparent border-0 outline-none tabular-nums"
        />
        <button
          type="button"
          disabled={disabled || value >= max}
          onClick={() => onChange(clamp(value + 1))}
          className="size-7 flex items-center justify-center rounded-md border border-border text-muted-foreground active:bg-elevated disabled:opacity-30"
        >
          +
        </button>
        {unit ? <span className="text-xs text-muted-foreground w-6">{unit}</span> : null}
      </div>
    </div>
  );
}

export function SettingsScreen({ onBack }: SettingsScreenProps): React.JSX.Element {
  const t = useTranslations("settings");
  const locale = useLocale() as SupportedLocale;
  const enabled = usePreferencesStore((s) => s.shiftCloseBiometricEnabled);
  const setEnabled = usePreferencesStore((s) => s.setShiftCloseBiometricEnabled);
  const supported = isShiftCloseBiometricSupported();
  const me = useAuthStore((s) => s.me);
  const clearAuth = useAuthStore((s) => s.clear);

  const handleLocaleChange = React.useCallback((next: SupportedLocale) => {
    if (next === locale) return;
    setLocaleCookie(next);
    window.location.reload();
  }, [locale]);

  const handleLogout = React.useCallback(() => {
    clearAuth();
    window.location.reload();
  }, [clearAuth]);

  React.useEffect(() => {
    if (!supported && enabled) {
      setEnabled(false);
    }
  }, [supported, enabled, setEnabled]);

  return (
    <main className="mx-auto max-w-md px-4 pt-4 pb-24 animate-fade-in-up">
      <header className="mb-4 flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={onBack} className="-ml-2 px-2">
          <ArrowLeft className="size-5" />
        </Button>
        <div className="flex-1">
          <h1 className="text-lg font-semibold">{t("title")}</h1>
          <p className="text-xs text-muted-foreground">{t("subtitle")}</p>
        </div>
      </header>

      {/* Account info */}
      {me ? (
        <Card className="mb-3">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <User className="size-5 text-muted-foreground" />
              {t("account.title")}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex items-center justify-between rounded-lg bg-elevated/40 px-3 py-2.5">
              <span className="text-sm text-muted-foreground">{t("account.name")}</span>
              <span className="text-sm font-medium">{me.fullName}</span>
            </div>
            <div className="flex items-center justify-between rounded-lg bg-elevated/40 px-3 py-2.5">
              <span className="text-sm text-muted-foreground">{t("account.role")}</span>
              <span className="text-sm font-medium">
                {ROLE_LABELS[me.role] ?? me.role}
              </span>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {/* Biometric */}
      <Card className="mb-3">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Fingerprint className="size-5 text-muted-foreground" />
            {t("biometric.title")}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">{t("biometric.body")}</p>
          {!supported ? (
            <p className="text-xs text-muted-foreground">{t("biometric.unsupported")}</p>
          ) : null}
          <label className="flex cursor-pointer items-center justify-between gap-4 rounded-lg border border-border bg-elevated/40 px-3 py-3">
            <span className="text-sm font-medium">{t("biometric.toggle")}</span>
            <input
              type="checkbox"
              className="size-5 accent-primary"
              checked={enabled && supported}
              disabled={!supported}
              onChange={(e) => setEnabled(e.target.checked)}
            />
          </label>
        </CardContent>
      </Card>

      {/* Language */}
      <Card className="mb-3">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Languages className="size-5 text-muted-foreground" />
            {t("language.title")}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex gap-2">
            {(["ru", "en"] as SupportedLocale[]).map((l) => (
              <button
                key={l}
                type="button"
                onClick={() => handleLocaleChange(l)}
                className={[
                  "flex-1 rounded-lg border px-3 py-2.5 text-sm font-medium transition-colors",
                  locale === l
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border bg-elevated/40 text-muted-foreground active:bg-elevated",
                ].join(" ")}
              >
                {t(`language.${l}`)}
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Notification prefs — owner only */}
      {me?.role === "owner" ? <NotificationPrefsCard /> : null}

      {/* About */}
      <Card className="mb-3">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <BadgeInfo className="size-5 text-muted-foreground" />
            {t("about.title")}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <div className="flex items-center justify-between rounded-lg bg-elevated/40 px-3 py-2.5">
            <span className="text-sm text-muted-foreground">{t("about.app")}</span>
            <span className="text-sm font-medium">ShiftOps</span>
          </div>
          <p className="text-xs text-muted-foreground px-1">{t("about.hint")}</p>
        </CardContent>
      </Card>

      {/* Logout */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <LogOut className="size-5 text-muted-foreground" />
            {t("logout.button")}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-xs text-muted-foreground px-1">{t("logout.hint")}</p>
          <Button variant="danger" size="block" onClick={handleLogout}>
            {t("logout.button")}
          </Button>
        </CardContent>
      </Card>
    </main>
  );
}
