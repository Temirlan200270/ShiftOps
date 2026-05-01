"use client";

import { ArrowLeft, Fingerprint } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { isShiftCloseBiometricSupported } from "@/lib/telegram/biometric";
import { usePreferencesStore } from "@/lib/stores/preferences-store";

interface SettingsScreenProps {
  onBack: () => void;
}

export function SettingsScreen({ onBack }: SettingsScreenProps): React.JSX.Element {
  const t = useTranslations("settings");
  const enabled = usePreferencesStore((s) => s.shiftCloseBiometricEnabled);
  const setEnabled = usePreferencesStore((s) => s.setShiftCloseBiometricEnabled);
  const supported = isShiftCloseBiometricSupported();

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

      <Card>
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
    </main>
  );
}
