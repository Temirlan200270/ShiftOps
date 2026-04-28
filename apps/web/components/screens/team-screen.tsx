"use client";

import { Sparkles, Users } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  createInvite,
  fetchLocations,
  fetchTeamMembers,
  fetchTeamSummary,
  type LocationRow,
  type TeamMemberRow,
} from "@/lib/api/invites";
import { useAuthStore } from "@/lib/stores/auth-store";
import { toast } from "@/lib/stores/toast-store";
import { haptic, notify } from "@/lib/telegram/init";

type TeamScreenProps = {
  onBack: () => void;
};

export function TeamScreen({ onBack }: TeamScreenProps): React.JSX.Element {
  const t = useTranslations("team");
  const tErr = useTranslations("errors");
  const me = useAuthStore((s) => s.me);
  const isOwner = me?.role === "owner";
  const [locations, setLocations] = React.useState<LocationRow[]>([]);
  const [members, setMembers] = React.useState<TeamMemberRow[] | null>(null);
  const [loadingLocs, setLoadingLocs] = React.useState(true);
  const [otherMembersCount, setOtherMembersCount] = React.useState<number | null>(null);
  const [role, setRole] = React.useState<"admin" | "operator">("operator");
  const [locationId, setLocationId] = React.useState<string>("");
  const [expiresH, setExpiresH] = React.useState(48);
  const [generating, setGenerating] = React.useState(false);
  const [deepLink, setDeepLink] = React.useState<string | null>(null);
  const [expiresAt, setExpiresAt] = React.useState<string | null>(null);
  const [copied, setCopied] = React.useState(false);
  const formRef = React.useRef<HTMLDivElement>(null);
  const [membersFetchError, setMembersFetchError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!isOwner) {
      setRole("operator");
    }
  }, [isOwner]);

  React.useEffect(() => {
    void (async () => {
      setLoadingLocs(true);
      setMembersFetchError(null);

      const [locR, teamR, memR] = await Promise.all([
        fetchLocations(),
        fetchTeamSummary(),
        fetchTeamMembers(false),
      ]);

      if (locR.ok) {
        setLocations(locR.data);
      } else {
        setLocations([]);
      }

      if (teamR.ok) {
        setOtherMembersCount(teamR.data.other_members_count);
      } else {
        setOtherMembersCount(-1);
      }

      if (memR.ok) {
        setMembers(memR.data);
      } else {
        setMembers([]);
      }

      let toastShown = false;
      if (!locR.ok) {
        toastShown = true;
        toast({
          variant: "critical",
          title: tErr("generic"),
          description: locR.message,
        });
      }
      if (!toastShown && !teamR.ok) {
        toastShown = true;
        toast({
          variant: "critical",
          title: tErr("generic"),
          description: teamR.message,
        });
      }
      if (!toastShown && !memR.ok) {
        setMembersFetchError(t("membersLoadFailed"));
      }

      setLoadingLocs(false);
    })();
  }, [t, tErr]);

  const alone = otherMembersCount === 0;
  const showEmpty = !loadingLocs && otherMembersCount !== null && alone;

  const scrollToInviteForm = React.useCallback(() => {
    haptic("medium");
    formRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  const copyToClipboard = React.useCallback(
    async (url: string) => {
      haptic("light");
      try {
        await navigator.clipboard.writeText(url);
        setCopied(true);
        setTimeout(() => {
          setCopied(false);
        }, 2500);
        return true;
      } catch {
        toast({ variant: "critical", title: tErr("generic") });
        return false;
      }
    },
    [tErr],
  );

  const handleGenerate = React.useCallback(async () => {
    haptic("medium");
    setGenerating(true);
    setCopied(false);
    setDeepLink(null);
    setExpiresAt(null);
    const r = await createInvite({
      role,
      location_id: locationId === "" ? null : locationId,
      expires_in_hours: Math.min(168, Math.max(1, Math.floor(expiresH))),
    });
    setGenerating(false);
    if (r.ok) {
      setDeepLink(r.data.deep_link);
      setExpiresAt(r.data.expires_at);
      notify("success");
      haptic("medium");
      try {
        await navigator.clipboard.writeText(r.data.deep_link);
        setCopied(true);
        setTimeout(() => {
          setCopied(false);
        }, 2500);
        toast({ variant: "success", title: t("autoCopied"), duration: 2500 });
      } catch {
        toast({ variant: "critical", title: tErr("generic") });
      }
    } else {
      toast({ variant: "critical", title: tErr("generic"), description: r.message });
    }
  }, [expiresH, locationId, role, t, tErr]);

  return (
    <main className="mx-auto max-w-md px-4 pt-6 pb-24 animate-fade-in-up">
      <header className="mb-6">
        <Button variant="ghost" className="mb-2 -ml-2" onClick={onBack} type="button">
          ←
        </Button>
        <div className="flex items-center gap-2">
          <Users className="size-6 text-primary" />
          <h1 className="text-2xl font-semibold">{t("title")}</h1>
        </div>
        <p className="text-sm text-muted-foreground mt-1">{t("subtitle")}</p>
      </header>

      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="text-base">{t("membersTitle")}</CardTitle>
        </CardHeader>
        <CardContent className={members === null || loadingLocs ? "animate-pulse" : undefined}>
          {members === null || loadingLocs ? (
            <p className="text-sm text-muted-foreground">{t("membersLoading")}</p>
          ) : membersFetchError ? (
            <p className="text-sm text-critical">{membersFetchError}</p>
          ) : members.length === 0 ? (
            <p className="text-sm text-muted-foreground">—</p>
          ) : (
            <ul className="space-y-0 divide-y divide-border/60" aria-label={t("membersTitle")}>
              {members.map((member) => {
                const roleKey = member.role as "owner" | "admin" | "operator";
                const badge =
                  roleKey === "owner"
                    ? t("roleOwner")
                    : roleKey === "admin"
                      ? t("roleAdmin")
                      : roleKey === "operator"
                        ? t("roleOperator")
                        : member.role;
                const isSelf = member.id === me?.id;
                return (
                  <li
                    key={member.id}
                    className="flex flex-wrap items-start justify-between gap-2 py-3 first:pt-0 last:pb-0"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="font-medium leading-snug break-words">
                        {member.full_name}
                        {isSelf ? (
                          <span className="text-muted-foreground font-normal text-xs ms-1.5">{t("memberYou")}</span>
                        ) : null}
                      </p>
                      {member.tg_username ? (
                        <p className="text-xs text-muted-foreground mt-0.5 truncate">@{member.tg_username}</p>
                      ) : null}
                    </div>
                    <span className="shrink-0 text-xs uppercase tracking-wide text-muted-foreground border border-border rounded-full px-2 py-0.5 whitespace-nowrap">
                      {badge}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>

      {showEmpty ? (
        <section
          className="mb-6 rounded-2xl border border-dashed border-border/80 bg-elevated/50 px-5 py-10 text-center"
          aria-label={t("emptyTitle")}
        >
          <div className="mx-auto mb-4 flex size-16 items-center justify-center rounded-2xl bg-primary/10 text-primary">
            <Users className="size-8" />
          </div>
          <h2 className="text-lg font-semibold mb-2">{t("emptyTitle")}</h2>
          <p className="text-sm text-muted-foreground mb-6 max-w-sm mx-auto leading-relaxed">
            {t("emptyBody")}
          </p>
          <Button
            type="button"
            size="block"
            onClick={scrollToInviteForm}
            className="max-w-xs mx-auto"
          >
            <Sparkles className="size-4" />
            {t("emptyCta")}
          </Button>
        </section>
      ) : null}

      <div ref={formRef} id="team-invite-form">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t("roleLabel")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid gap-2">
              {isOwner ? (
                <>
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="radio"
                      name="role"
                      checked={role === "admin"}
                      onChange={() => {
                        setRole("admin");
                      }}
                    />
                    {t("roleAdmin")}
                  </label>
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="radio"
                      name="role"
                      checked={role === "operator"}
                      onChange={() => {
                        setRole("operator");
                      }}
                    />
                    {t("roleOperator")}
                  </label>
                </>
              ) : (
                <p className="text-sm text-muted-foreground">{t("roleOperator")}</p>
              )}
            </div>

            <div>
              <label className="text-sm text-muted-foreground block mb-1" htmlFor="loc">
                {t("locationLabel")}
              </label>
              <select
                id="loc"
                className="w-full rounded-md border border-border bg-elevated px-3 py-2 text-sm"
                value={locationId}
                onChange={(e) => {
                  setLocationId(e.target.value);
                }}
                disabled={loadingLocs}
              >
                <option value="">{t("locationAny")}</option>
                {locations.map((loc) => (
                  <option key={loc.id} value={loc.id}>
                    {loc.name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="text-sm text-muted-foreground block mb-1" htmlFor="ex">
                {t("expiresLabel")}
              </label>
              <input
                id="ex"
                type="number"
                min={1}
                max={168}
                className="w-full rounded-md border border-border bg-elevated px-3 py-2 text-sm"
                value={expiresH}
                onChange={(e) => {
                  setExpiresH(Number(e.target.value) || 48);
                }}
              />
            </div>

            <Button
              size="block"
              type="button"
              onClick={() => {
                void handleGenerate();
              }}
              disabled={generating}
            >
              {generating ? t("generating") : t("generate")}
            </Button>
          </CardContent>
        </Card>
      </div>

      {deepLink ? (
        <Card className="mt-4">
          <CardHeader>
            <CardTitle className="text-base">{t("linkLabel")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <p className="text-xs break-all text-muted-foreground font-mono">{deepLink}</p>
            {expiresAt ? (
              <p className="text-sm text-muted-foreground">
                {t("expiresAt", {
                  date: new Date(expiresAt).toLocaleString(),
                })}
              </p>
            ) : null}
            <div className="flex gap-2">
              <Button
                type="button"
                variant="secondary"
                size="md"
                onClick={() => void copyToClipboard(deepLink)}
              >
                {copied ? t("copied") : t("copy")}
              </Button>
            </div>
            <p className="text-sm text-muted-foreground">{t("hint")}</p>
          </CardContent>
        </Card>
      ) : null}
    </main>
  );
}
