"use client";

import { Loader2, RotateCw } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { DashboardScreen } from "@/components/screens/dashboard-screen";
import { Button } from "@/components/ui/button";
import { performHandshake } from "@/lib/auth/handshake";
import { useAuthStore } from "@/lib/stores/auth-store";

/**
 * Root page → either splash (S0), dashboard (S1) or downstream screens.
 *
 * The router stays single-route on purpose: TWA back navigation is awkward
 * when the URL changes (Telegram uses its own back button), so we drive
 * screens with local React state instead.
 */
export default function Page(): React.JSX.Element {
  const me = useAuthStore((s) => s.me);
  const [retrying, setRetrying] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const tSplash = useTranslations("splash");

  const handleRetry = React.useCallback(async () => {
    setRetrying(true);
    setError(null);
    try {
      await performHandshake();
    } catch (err) {
      setError(err instanceof Error ? err.message : "unknown");
    } finally {
      setRetrying(false);
    }
  }, []);

  if (!me) {
    return (
      <main className="min-h-screen flex flex-col items-center justify-center px-6 text-center">
        <div className="size-14 rounded-md bg-elevated grid place-items-center mb-4">
          <Loader2 className="size-7 animate-spin text-primary" />
        </div>
        <h1 className="text-xl font-semibold mb-1">ShiftOps</h1>
        <p className="text-muted-foreground text-sm">{tSplash("loading")}</p>
        {error ? (
          <div className="mt-6 rounded-md border border-critical/30 bg-critical/10 p-4 text-sm">
            <p className="font-medium text-critical mb-1">{tSplash("errorTitle")}</p>
            <p className="text-muted-foreground">{tSplash("errorBody")}</p>
            <Button
              variant="secondary"
              size="md"
              className="mt-3"
              onClick={handleRetry}
              disabled={retrying}
            >
              <RotateCw className="size-4" />
              {tSplash("retry")}
            </Button>
          </div>
        ) : null}
      </main>
    );
  }

  return <DashboardScreen />;
}
