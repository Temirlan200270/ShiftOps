"use client";

import { MoreVertical, Sparkles, Trash2, UserCog, Users } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import {
  changeMemberRole,
  createInvite,
  fetchLocations,
  fetchTeamMembers,
  fetchTeamSummary,
  removeMember,
  type LocationRow,
  type ManageableRole,
  type TeamMemberRow,
} from "@/lib/api/invites";
import { useAuthStore } from "@/lib/stores/auth-store";
import { toast } from "@/lib/stores/toast-store";
import { haptic, notify } from "@/lib/telegram/init";

type TeamScreenProps = {
  onBack: () => void;
};

type ManageErrorKey =
  | "cannot_manage_self"
  | "cannot_manage_super_admin"
  | "insufficient_role"
  | "cannot_change_owner_role"
  | "user_not_found"
  | "already_inactive"
  | "invalid_target_role";

const KNOWN_MANAGE_ERRORS = new Set<ManageErrorKey>([
  "cannot_manage_self",
  "cannot_manage_super_admin",
  "insufficient_role",
  "cannot_change_owner_role",
  "user_not_found",
  "already_inactive",
  "invalid_target_role",
]);

function extractErrorCode(raw: string | null | undefined): string | null {
  if (!raw) return null;
  // Backend serializes detail as "code: message" — keep just the code.
  const head = raw.split(":", 1)[0]?.trim();
  return head || raw;
}

/** Whether to show the per-row ⋯ menu (change role / remove). */
function rowHasTeamActions(
  member: TeamMemberRow,
  me: { id: string; role: string } | null | undefined,
): boolean {
  const isSelf = member.id === me?.id;
  if (member.can_change_role === true || member.can_deactivate === true) {
    return true;
  }
  const serverSentFlags =
    typeof member.can_change_role === "boolean" ||
    typeof member.can_deactivate === "boolean";
  if (serverSentFlags) {
    return false;
  }
  // Старый API без полей can_*: иначе `undefined || undefined` скрывает меню.
  // Сервер всё равно проверит права на POST; здесь только подсказка UI для owner.
  return me?.role === "owner" && !isSelf;
}

function sheetCanRemoveMember(
  member: TeamMemberRow,
  me: { id: string; role: string } | null | undefined,
): boolean {
  if (member.can_deactivate === true) return true;
  if (typeof member.can_deactivate === "boolean") return false;
  return me?.role === "owner" && member.id !== me?.id;
}

function sheetCanChangeRoleMember(
  member: TeamMemberRow,
  me: { id: string; role: string } | null | undefined,
): boolean {
  if (member.can_change_role === true) return true;
  if (typeof member.can_change_role === "boolean") return false;
  if (member.role === "owner") return false;
  return me?.role === "owner" && member.id !== me?.id;
}

export function TeamScreen({ onBack }: TeamScreenProps): React.JSX.Element {
  const t = useTranslations("team");
  const tErr = useTranslations("errors");
  const me = useAuthStore((s) => s.me);
  const isOwner = me?.role === "owner";
  const [locations, setLocations] = React.useState<LocationRow[]>([]);
  const [members, setMembers] = React.useState<TeamMemberRow[] | null>(null);
  const [loadingLocs, setLoadingLocs] = React.useState(true);
  const [otherMembersCount, setOtherMembersCount] = React.useState<number | null>(null);
  const [role, setRole] = React.useState<ManageableRole>("operator");
  const [locationId, setLocationId] = React.useState<string>("");
  const [expiresH, setExpiresH] = React.useState(48);
  const [generating, setGenerating] = React.useState(false);
  const [deepLink, setDeepLink] = React.useState<string | null>(null);
  const [expiresAt, setExpiresAt] = React.useState<string | null>(null);
  const [copied, setCopied] = React.useState(false);
  const formRef = React.useRef<HTMLDivElement>(null);
  const [membersFetchError, setMembersFetchError] = React.useState<string | null>(null);

  // Action-menu / modals state
  const [actionMember, setActionMember] = React.useState<TeamMemberRow | null>(null);
  const [roleSheet, setRoleSheet] = React.useState<TeamMemberRow | null>(null);
  const [removeSheet, setRemoveSheet] = React.useState<TeamMemberRow | null>(null);
  const [pendingRole, setPendingRole] = React.useState<ManageableRole>("operator");
  const [savingRole, setSavingRole] = React.useState(false);
  const [removing, setRemoving] = React.useState(false);

  const translateManageError = React.useCallback(
    (code: string | null | undefined, fallback: string | null): string => {
      const c = code as ManageErrorKey | null;
      if (c && KNOWN_MANAGE_ERRORS.has(c)) {
        return t(`manageErrors.${c}`);
      }
      return fallback ?? tErr("generic");
    },
    [t, tErr],
  );

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

  const reloadMembers = React.useCallback(async () => {
    const memR = await fetchTeamMembers(false);
    if (memR.ok) {
      setMembers(memR.data);
    }
  }, []);

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

  const openActionMenu = React.useCallback((m: TeamMemberRow) => {
    haptic("light");
    setActionMember(m);
  }, []);

  const closeActionMenu = React.useCallback(() => {
    setActionMember(null);
  }, []);

  const openRoleEditor = React.useCallback((m: TeamMemberRow) => {
    setActionMember(null);
    const initial: ManageableRole =
      m.role === "admin" ? "admin" : m.role === "bartender" ? "bartender" : "operator";
    setPendingRole(initial);
    setRoleSheet(m);
  }, []);

  const openRemoveConfirm = React.useCallback((m: TeamMemberRow) => {
    setActionMember(null);
    setRemoveSheet(m);
  }, []);

  const handleSaveRole = React.useCallback(async () => {
    if (!roleSheet) return;
    setSavingRole(true);
    const r = await changeMemberRole(roleSheet.id, pendingRole);
    setSavingRole(false);
    if (r.ok) {
      notify("success");
      toast({ variant: "success", title: t("changeRole.saved"), duration: 2500 });
      setRoleSheet(null);
      void reloadMembers();
    } else {
      const code = extractErrorCode(r.code);
      toast({
        variant: "critical",
        title: tErr("generic"),
        description: translateManageError(code, r.message),
      });
    }
  }, [pendingRole, reloadMembers, roleSheet, t, tErr, translateManageError]);

  const handleConfirmRemove = React.useCallback(async () => {
    if (!removeSheet) return;
    setRemoving(true);
    const r = await removeMember(removeSheet.id);
    setRemoving(false);
    if (r.ok) {
      notify("success");
      toast({ variant: "success", title: t("remove.removed"), duration: 2500 });
      setRemoveSheet(null);
      void reloadMembers();
    } else {
      const code = extractErrorCode(r.code);
      toast({
        variant: "critical",
        title: tErr("generic"),
        description: translateManageError(code, r.message),
      });
    }
  }, [reloadMembers, removeSheet, t, tErr, translateManageError]);

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
                const roleKey = member.role as "owner" | "admin" | "operator" | "bartender";
                const badge =
                  roleKey === "owner"
                    ? t("roleOwner")
                    : roleKey === "admin"
                      ? t("roleAdmin")
                      : roleKey === "operator"
                        ? t("roleOperator")
                        : roleKey === "bartender"
                          ? t("roleBartender")
                          : member.role;
                const isSelf = member.id === me?.id;
                const showActions = rowHasTeamActions(member, me);
                return (
                  <li
                    key={member.id}
                    className="flex flex-wrap items-start justify-between gap-2 py-3 first:pt-0 last:pb-0"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="font-medium leading-snug break-words">
                        {member.full_name}
                        {isSelf ? (
                          <span className="text-muted-foreground font-normal text-xs ms-1.5">
                            {t("memberYou")}
                          </span>
                        ) : null}
                      </p>
                      {member.tg_username ? (
                        <p className="text-xs text-muted-foreground mt-0.5 truncate">
                          @{member.tg_username}
                        </p>
                      ) : null}
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <span className="text-xs uppercase tracking-wide text-muted-foreground border border-border rounded-full px-2 py-0.5 whitespace-nowrap">
                        {badge}
                      </span>
                      {showActions ? (
                        <button
                          type="button"
                          onClick={() => {
                            openActionMenu(member);
                          }}
                          className="rounded-full p-1 text-muted-foreground hover:bg-elevated focus:outline-none focus:ring-2 focus:ring-primary/40"
                          aria-label={t("actions.open")}
                          title={t("actions.open")}
                        >
                          <MoreVertical className="size-4" />
                        </button>
                      ) : null}
                    </div>
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
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="radio"
                      name="role"
                      checked={role === "bartender"}
                      onChange={() => {
                        setRole("bartender");
                      }}
                    />
                    {t("roleBartender")}
                  </label>
                </>
              ) : (
                <>
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
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="radio"
                      name="role"
                      checked={role === "bartender"}
                      onChange={() => {
                        setRole("bartender");
                      }}
                    />
                    {t("roleBartender")}
                  </label>
                </>
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

      {/* Per-member action menu */}
      <Sheet
        open={actionMember !== null}
        onOpenChange={(open: boolean) => {
          if (!open) closeActionMenu();
        }}
      >
        <SheetContent title={t("actions.label")}>
          {actionMember ? (
            <div className="flex flex-col gap-2">
              <Button
                type="button"
                variant="secondary"
                size="block"
                disabled={!sheetCanChangeRoleMember(actionMember, me)}
                onClick={() => {
                  if (sheetCanChangeRoleMember(actionMember, me)) openRoleEditor(actionMember);
                }}
              >
                <UserCog className="size-4" />
                {t("actions.changeRole")}
              </Button>
              {!sheetCanChangeRoleMember(actionMember, me) &&
              (actionMember.cannot_change_role_reason ||
                (actionMember.role === "owner" &&
                  typeof actionMember.can_change_role !== "boolean")) ? (
                <p className="text-xs text-muted-foreground -mt-1">
                  {translateManageError(
                    actionMember.cannot_change_role_reason ?? "cannot_change_owner_role",
                    null,
                  )}
                </p>
              ) : null}

              <Button
                type="button"
                variant="danger"
                size="block"
                disabled={!sheetCanRemoveMember(actionMember, me)}
                onClick={() => {
                  if (sheetCanRemoveMember(actionMember, me)) openRemoveConfirm(actionMember);
                }}
              >
                <Trash2 className="size-4" />
                {t("actions.remove")}
              </Button>
              {!sheetCanRemoveMember(actionMember, me) && actionMember.cannot_deactivate_reason ? (
                <p className="text-xs text-muted-foreground -mt-1">
                  {translateManageError(
                    actionMember.cannot_deactivate_reason,
                    null,
                  )}
                </p>
              ) : null}
            </div>
          ) : null}
        </SheetContent>
      </Sheet>

      {/* Change role */}
      <Sheet
        open={roleSheet !== null}
        onOpenChange={(open: boolean) => {
          if (!open) setRoleSheet(null);
        }}
      >
        <SheetContent title={t("changeRole.title")}>
          {roleSheet ? (
            <div className="flex flex-col gap-3">
              <p className="text-sm text-muted-foreground">{t("changeRole.description")}</p>
              <div className="grid gap-2">
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="radio"
                    name="member-role"
                    checked={pendingRole === "admin"}
                    onChange={() => {
                      setPendingRole("admin");
                    }}
                  />
                  {t("changeRole.selectAdmin")}
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="radio"
                    name="member-role"
                    checked={pendingRole === "operator"}
                    onChange={() => {
                      setPendingRole("operator");
                    }}
                  />
                  {t("changeRole.selectOperator")}
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="radio"
                    name="member-role"
                    checked={pendingRole === "bartender"}
                    onChange={() => {
                      setPendingRole("bartender");
                    }}
                  />
                  {t("changeRole.selectBartender")}
                </label>
              </div>
              <Button
                type="button"
                size="block"
                disabled={savingRole}
                onClick={() => {
                  void handleSaveRole();
                }}
              >
                {savingRole ? t("changeRole.saving") : t("changeRole.save")}
              </Button>
            </div>
          ) : null}
        </SheetContent>
      </Sheet>

      {/* Remove member */}
      <Sheet
        open={removeSheet !== null}
        onOpenChange={(open: boolean) => {
          if (!open) setRemoveSheet(null);
        }}
      >
        <SheetContent title={t("remove.title")}>
          {removeSheet ? (
            <div className="flex flex-col gap-3">
              <p className="text-sm text-muted-foreground">
                {t("remove.description", { name: removeSheet.full_name })}
              </p>
              <Button
                type="button"
                size="block"
                variant="danger"
                disabled={removing}
                onClick={() => {
                  void handleConfirmRemove();
                }}
              >
                {removing ? t("remove.removing") : t("remove.confirm")}
              </Button>
              <Button
                type="button"
                size="block"
                variant="secondary"
                disabled={removing}
                onClick={() => {
                  setRemoveSheet(null);
                }}
              >
                {t("remove.cancelLabel")}
              </Button>
            </div>
          ) : null}
        </SheetContent>
      </Sheet>
    </main>
  );
}
