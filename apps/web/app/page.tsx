"use client";

import { Loader2, RotateCw } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { DashboardScreen } from "@/components/screens/dashboard-screen";
import { Button } from "@/components/ui/button";
import { HandshakeError, performHandshake } from "@/lib/auth/handshake";
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
  const accessToken = useAuthStore((s) => s.accessToken);
  const authBootstrapComplete = useAuthStore((s) => s.authBootstrapComplete);
  const handshakeError = useAuthStore((s) => s.handshakeError);
  const handshakeErrorCode = useAuthStore((s) => s.handshakeErrorCode);
  const setHandshakeError = useAuthStore((s) => s.setHandshakeError);
  const [retrying, setRetrying] = React.useState(false);
  const tSplash = useTranslations("splash");

  const handleRetry = React.useCallback(async () => {
    setRetrying(true);
    setHandshakeError(null);
    try {
      await performHandshake();
    } catch (err) {
      if (err instanceof HandshakeError) {
        setHandshakeError(err.message, err.code);
      } else {
        setHandshakeError(err instanceof Error ? err.message : "unknown", null);
      }
    } finally {
      setRetrying(false);
    }
  }, [setHandshakeError]);

  if (!authBootstrapComplete || !me || !accessToken) {
    return (
      <main className="min-h-screen flex flex-col items-center justify-center px-6 text-center">
        <div className="size-14 rounded-md bg-elevated grid place-items-center mb-4">
          {retrying || !handshakeError ? (
            <Loader2 className="size-7 animate-spin text-primary" />
          ) : (
            <div className="size-7 rounded-sm bg-critical/20" aria-hidden />
          )}
        </div>
        <h1 className="text-xl font-semibold mb-1">ShiftOps</h1>
        <p className="text-muted-foreground text-sm">{tSplash("loading")}</p>
        {handshakeError ? (
          <div className="mt-6 rounded-md border border-critical/30 bg-critical/10 p-4 text-sm">
            <p className="font-medium text-critical mb-1">{tSplash("errorTitle")}</p>
            <p className="text-muted-foreground break-words">
              {handshakeErrorCode === "invalid_init_data" ||
              /auth_date too old/i.test(handshakeError)
                ? tSplash("initDataExpiredHint")
                : handshakeError}
            </p>
            {handshakeErrorCode !== "invalid_init_data" && !/auth_date too old/i.test(handshakeError) ? (
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
            ) : null}
          </div>
        ) : null}
      </main>
    );
  }

  return <DashboardScreen />;
}
