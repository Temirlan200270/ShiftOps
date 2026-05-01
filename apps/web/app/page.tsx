"use client";

import { Loader2, RotateCw } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { DashboardScreen } from "@/components/screens/dashboard-screen";
import { OnboardingScreen, hasSeenOnboarding } from "@/components/screens/onboarding-screen";
import { Button } from "@/components/ui/button";
import { runBootstrapAuthSession } from "@/lib/auth/bootstrap-session";
import { useAuthStore } from "@/lib/stores/auth-store";

/**
 * Root page → either splash (S0), dashboard (S1) or downstream screens.
 *
 * Session latch: after a successful `me` + access token, we do not force a
 * full-screen splash if the access token is temporarily empty but a refresh
 * token still exists (client will mint a new access JWT). This avoids UI
 * flicker while staying strict on first load and full logout.
 */
export default function Page(): React.JSX.Element {
  const me = useAuthStore((s) => s.me);
  const accessToken = useAuthStore((s) => s.accessToken);
  const refreshToken = useAuthStore((s) => s.refreshToken);
  const authBootstrapComplete = useAuthStore((s) => s.authBootstrapComplete);
  const handshakeError = useAuthStore((s) => s.handshakeError);
  const handshakeErrorCode = useAuthStore((s) => s.handshakeErrorCode);
  const setHandshakeError = useAuthStore((s) => s.setHandshakeError);
  const [retrying, setRetrying] = React.useState(false);
  const [sessionLatched, setSessionLatched] = React.useState(false);
  // `null` until we've checked localStorage on the client; this avoids a
  // hydration flash where onboarding briefly renders for already-seen users.
  const [showOnboarding, setShowOnboarding] = React.useState<boolean | null>(null);
  const tSplash = useTranslations("splash");

  React.useEffect(() => {
    setShowOnboarding(!hasSeenOnboarding());
  }, []);

  React.useEffect(() => {
    if (me?.id && accessToken) {
      setSessionLatched(true);
      return;
    }
    if (!me && !accessToken && !refreshToken) {
      setSessionLatched(false);
    }
  }, [me, accessToken, refreshToken]);

  const showBlockingSplash =
    !authBootstrapComplete ||
    ((!me || !accessToken) &&
      (!sessionLatched || !me || (!accessToken && !refreshToken)));

  const handleAuthRetry = React.useCallback(async () => {
    setRetrying(true);
    setHandshakeError(null);
    try {
      await runBootstrapAuthSession();
    } finally {
      setRetrying(false);
    }
  }, [setHandshakeError]);

  const showSignInAgainCta =
    authBootstrapComplete &&
    !handshakeError &&
    !me &&
    !accessToken &&
    !refreshToken;

  if (showBlockingSplash) {
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
        {showSignInAgainCta ? (
          <div className="mt-8 max-w-sm">
            <p className="text-muted-foreground text-sm mb-3">{tSplash("signInAgainHint")}</p>
            <Button
              variant="primary"
              size="md"
              onClick={handleAuthRetry}
              disabled={retrying}
            >
              <RotateCw className={`size-4 ${retrying ? "animate-spin" : ""}`} />
              {tSplash("signInAgain")}
            </Button>
          </div>
        ) : null}
        {handshakeError ? (
          <div className="mt-6 rounded-md border border-critical/30 bg-critical/10 p-4 text-sm">
            <p className="font-medium text-critical mb-1">{tSplash("errorTitle")}</p>
            <p className="text-muted-foreground break-words">
              {handshakeErrorCode === "invalid_init_data" ||
              /auth_date too old/i.test(handshakeError)
                ? tSplash("initDataExpiredHint")
                : handshakeErrorCode === "user_inactive"
                  ? tSplash("userInactiveHint")
                  : handshakeErrorCode === "ask_admin_to_invite" ||
                      handshakeError.includes("ask_admin_to_invite")
                    ? tSplash("inviteRequiredHint")
                    : handshakeError}
            </p>
            {handshakeErrorCode !== "invalid_init_data" &&
            handshakeErrorCode !== "user_inactive" &&
            !/auth_date too old/i.test(handshakeError) ? (
              <Button
                variant="secondary"
                size="md"
                className="mt-3"
                onClick={handleAuthRetry}
                disabled={retrying}
              >
                <RotateCw className={`size-4 ${retrying ? "animate-spin" : ""}`} />
                {tSplash("retry")}
              </Button>
            ) : null}
          </div>
        ) : null}
      </main>
    );
  }

  if (showOnboarding === true) {
    return (
      <OnboardingScreen
        onDone={() => {
          setShowOnboarding(false);
        }}
      />
    );
  }

  return <DashboardScreen />;
}
