"use client";

import { CheckCircle2, ChevronRight, ClipboardList, ShieldCheck, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { haptic } from "@/lib/telegram/init";

/**
 * First-launch onboarding: 3 stacked cards explaining ShiftOps before the
 * dashboard renders. Persisted via `localStorage` so we never block the user
 * twice on the same device.
 *
 * Why a sequence of three cards (and not a slider): the TWA viewport is
 * cramped and Telegram's swipe gesture can collide with horizontal carousels.
 * Stacked cards survive both portrait/landscape and keyboard nav.
 */

export const ONBOARDING_STORAGE_KEY = "shiftops:onboardingSeen";

type OnboardingScreenProps = {
  onDone: () => void;
};

export function OnboardingScreen({ onDone }: OnboardingScreenProps): React.JSX.Element {
  const t = useTranslations("onboarding");

  const handleDone = React.useCallback(() => {
    haptic("medium");
    try {
      localStorage.setItem(ONBOARDING_STORAGE_KEY, "1");
    } catch {
      // Private mode / disabled storage — onboarding will show again next time.
    }
    onDone();
  }, [onDone]);

  return (
    <main className="mx-auto max-w-md px-4 pt-8 pb-24 animate-fade-in-up">
      <header className="mb-6 text-center">
        <div className="mx-auto mb-3 flex size-14 items-center justify-center rounded-2xl bg-primary/10 text-primary">
          <Sparkles className="size-7" />
        </div>
        <h1 className="text-2xl font-semibold">{t("title")}</h1>
        <p className="text-sm text-muted-foreground mt-1">{t("subtitle")}</p>
      </header>

      <ol className="space-y-4 mb-8" aria-label={t("title")}>
        <li className="rounded-2xl border border-border/70 bg-elevated/60 p-4 flex gap-3">
          <ClipboardList className="size-6 text-primary shrink-0 mt-0.5" />
          <div className="min-w-0">
            <h2 className="font-medium leading-snug">{t("slide1.title")}</h2>
            <p className="text-sm text-muted-foreground mt-1 leading-relaxed">
              {t("slide1.body")}
            </p>
          </div>
        </li>
        <li className="rounded-2xl border border-border/70 bg-elevated/60 p-4 flex gap-3">
          <ShieldCheck className="size-6 text-primary shrink-0 mt-0.5" />
          <div className="min-w-0">
            <h2 className="font-medium leading-snug">{t("slide2.title")}</h2>
            <p className="text-sm text-muted-foreground mt-1 leading-relaxed">
              {t("slide2.body")}
            </p>
          </div>
        </li>
        <li className="rounded-2xl border border-border/70 bg-elevated/60 p-4 flex gap-3">
          <CheckCircle2 className="size-6 text-primary shrink-0 mt-0.5" />
          <div className="min-w-0">
            <h2 className="font-medium leading-snug">{t("slide3.title")}</h2>
            <p className="text-sm text-muted-foreground mt-1 leading-relaxed">
              {t("slide3.body")}
            </p>
          </div>
        </li>
      </ol>

      <Button type="button" size="block" onClick={handleDone}>
        {t("cta")}
        <ChevronRight className="size-4" />
      </Button>
    </main>
  );
}

export function hasSeenOnboarding(): boolean {
  if (typeof window === "undefined") return true;
  try {
    return localStorage.getItem(ONBOARDING_STORAGE_KEY) === "1";
  } catch {
    return true;
  }
}
