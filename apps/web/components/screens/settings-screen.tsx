"use client";

import { ArrowLeft, BadgeInfo, Fingerprint, Languages, LogOut, User } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
          <Button variant="destructive" size="block" onClick={handleLogout}>
            {t("logout.button")}
          </Button>
        </CardContent>
      </Card>
    </main>
  );
}
