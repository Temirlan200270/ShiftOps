"use client";

import { ArrowLeft } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  acceptSwapRequest,
  cancelSwapRequest,
  createSwapRequest,
  declineSwapRequest,
  fetchMyScheduledShifts,
  fetchSwapLinkPreview,
  fetchSwapRequests,
  type MyScheduledShift,
  type SwapLinkPreview,
  type SwapRequestRow,
} from "@/lib/api/shifts";
import { localiseApiFailure } from "@/lib/i18n/api-errors";
import { useAuthStore } from "@/lib/stores/auth-store";
import { toast } from "@/lib/stores/toast-store";
import { haptic, notify } from "@/lib/telegram/init";
import { buildSwapInviteTelegramStartUrl, shareSwapInviteUrl } from "@/lib/telegram/swap-invite";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function shortId(id: string): string {
  return id.slice(0, 8);
}

interface SwapRequestsScreenProps {
  onBack: () => void;
  /** Opened from ?swap_proposer_shift= (colleague flow). */
  deepLinkProposerShiftId?: string | null;
  onConsumedDeepLink?: () => void;
}

export function SwapRequestsScreen({
  onBack,
  deepLinkProposerShiftId = null,
  onConsumedDeepLink,
}: SwapRequestsScreenProps): React.JSX.Element {
  const t = useTranslations("swap");
  const tErr = useTranslations("errors");
  const me = useAuthStore((s) => s.me);

  const [loading, setLoading] = React.useState(true);
  const [myScheduled, setMyScheduled] = React.useState<MyScheduledShift[]>([]);
  const [incoming, setIncoming] = React.useState<SwapRequestRow[]>([]);
  const [outgoing, setOutgoing] = React.useState<SwapRequestRow[]>([]);

  const [proposerShiftId, setProposerShiftId] = React.useState<string>("");
  const [counterpartyShiftId, setCounterpartyShiftId] = React.useState("");
  const [message, setMessage] = React.useState("");
  const [creating, setCreating] = React.useState(false);
  const [actingId, setActingId] = React.useState<string | null>(null);
  const [linkPreview, setLinkPreview] = React.useState<SwapLinkPreview | null>(null);
  const [previewLoading, setPreviewLoading] = React.useState(false);
  const [counterpartyPickId, setCounterpartyPickId] = React.useState("");

  const loadAll = React.useCallback(async () => {
    setLoading(true);
    const [sched, inc, out] = await Promise.all([
      fetchMyScheduledShifts(),
      fetchSwapRequests("in"),
      fetchSwapRequests("out"),
    ]);
    if (sched.ok) {
      setMyScheduled(sched.data);
      setProposerShiftId((prev) => (prev ? prev : sched.data[0]?.id ?? ""));
    } else {
      toast({
        variant: "critical",
        title: tErr("generic"),
        description: localiseApiFailure(sched, tErr),
      });
    }
    if (inc.ok) setIncoming(inc.data);
    else {
      toast({
        variant: "critical",
        title: tErr("generic"),
        description: localiseApiFailure(inc, tErr),
      });
    }
    if (out.ok) setOutgoing(out.data);
    else {
      toast({
        variant: "critical",
        title: tErr("generic"),
        description: localiseApiFailure(out, tErr),
      });
    }
    setLoading(false);
  }, [tErr]);

  React.useEffect(() => {
    void loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  React.useEffect(() => {
    if (!deepLinkProposerShiftId) {
      setLinkPreview(null);
      return;
    }
    let cancelled = false;
    setPreviewLoading(true);
    void fetchSwapLinkPreview(deepLinkProposerShiftId).then((res) => {
      if (cancelled) return;
      setPreviewLoading(false);
      if (res.ok) {
        setLinkPreview(res.data);
      } else {
        toast({
          variant: "critical",
          title: tErr("generic"),
          description: localiseApiFailure(res, tErr),
        });
      }
    });
    return () => {
      cancelled = true;
    };
  }, [deepLinkProposerShiftId, tErr]);

  const handleShareInvite = React.useCallback(async () => {
    if (!proposerShiftId) return;
    const url = buildSwapInviteTelegramStartUrl(proposerShiftId);
    if (!url) {
      toast({ variant: "critical", title: t("shareNoBot") });
      return;
    }
    haptic("medium");
    const ok = await shareSwapInviteUrl(url, t("shareTitle"));
    toast({
      variant: ok ? "success" : "critical",
      title: ok ? t("shareCopiedOrShared") : t("shareFailed"),
    });
  }, [proposerShiftId, t]);

  const handleCreateFromDeepLink = React.useCallback(async () => {
    if (!deepLinkProposerShiftId || !counterpartyPickId.trim()) {
      return;
    }
    setCreating(true);
    haptic("medium");
    const result = await createSwapRequest({
      proposerShiftId: deepLinkProposerShiftId,
      counterpartyShiftId: counterpartyPickId.trim(),
      message: message.trim() || null,
    });
    setCreating(false);
    if (result.ok) {
      notify("success");
      toast({ variant: "success", title: t("created") });
      setMessage("");
      setCounterpartyPickId("");
      onConsumedDeepLink?.();
      await loadAll();
    } else {
      notify("error");
      toast({
        variant: "critical",
        title: tErr("generic"),
        description: localiseApiFailure(result, tErr),
      });
    }
  }, [
    counterpartyPickId,
    deepLinkProposerShiftId,
    loadAll,
    message,
    onConsumedDeepLink,
    t,
    tErr,
  ]);

  const handleCreate = React.useCallback(async () => {
    const trimmed = counterpartyShiftId.trim();
    if (!UUID_RE.test(trimmed)) {
      toast({ variant: "critical", title: t("invalidUuid") });
      return;
    }
    if (!proposerShiftId) {
      return;
    }
    setCreating(true);
    haptic("medium");
    const result = await createSwapRequest({
      proposerShiftId,
      counterpartyShiftId: trimmed,
      message: message.trim() || null,
    });
    setCreating(false);
    if (result.ok) {
      notify("success");
      toast({ variant: "success", title: t("created") });
      setCounterpartyShiftId("");
      setMessage("");
      await loadAll();
    } else {
      notify("error");
      toast({
        variant: "critical",
        title: tErr("generic"),
        description: localiseApiFailure(result, tErr),
      });
    }
  }, [counterpartyShiftId, message, proposerShiftId, loadAll, t, tErr]);

  const handleAccept = React.useCallback(
    async (id: string) => {
      setActingId(id);
      haptic("medium");
      const result = await acceptSwapRequest(id);
      setActingId(null);
      if (result.ok) {
        notify("success");
        toast({ variant: "success", title: t("resolved") });
        await loadAll();
      } else {
        notify("error");
        toast({
          variant: "critical",
          title: tErr("generic"),
          description: localiseApiFailure(result, tErr),
        });
      }
    },
    [loadAll, t, tErr],
  );

  const handleDecline = React.useCallback(
    async (id: string) => {
      setActingId(id);
      haptic("light");
      const result = await declineSwapRequest(id);
      setActingId(null);
      if (result.ok) {
        notify("success");
        toast({ variant: "success", title: t("resolved") });
        await loadAll();
      } else {
        notify("error");
        toast({
          variant: "critical",
          title: tErr("generic"),
          description: localiseApiFailure(result, tErr),
        });
      }
    },
    [loadAll, t, tErr],
  );

  const handleCancel = React.useCallback(
    async (id: string) => {
      setActingId(id);
      haptic("light");
      const result = await cancelSwapRequest(id);
      setActingId(null);
      if (result.ok) {
        notify("success");
        toast({ variant: "success", title: t("resolved") });
        await loadAll();
      } else {
        notify("error");
        toast({
          variant: "critical",
          title: tErr("generic"),
          description: localiseApiFailure(result, tErr),
        });
      }
    },
    [loadAll, t, tErr],
  );

  const statusLabel = React.useCallback(
    (status: string) => {
      const key = status as "pending" | "accepted" | "declined" | "cancelled" | "expired";
      if (key === "pending" || key === "accepted" || key === "declined" || key === "cancelled" || key === "expired") {
        return t(`status.${key}`);
      }
      return status;
    },
    [t],
  );

  return (
    <main className="mx-auto max-w-md px-4 pt-4 pb-24 animate-fade-in-up">
      <header className="flex items-center gap-3 mb-4">
        <Button variant="ghost" size="sm" onClick={onBack} className="-ml-2 px-2">
          <ArrowLeft className="size-5" />
        </Button>
        <div className="flex-1">
          <h1 className="text-lg font-semibold">{t("title")}</h1>
          <p className="text-xs text-muted-foreground">{t("subtitle")}</p>
        </div>
      </header>

      {loading ? (
        <Card className="animate-pulse">
          <CardContent className="p-6 h-32" />
        </Card>
      ) : (
        <>
          {deepLinkProposerShiftId ? (
            <Card className="mb-4">
              <CardHeader>
                <CardTitle className="text-base">{t("deepLinkTitle")}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {previewLoading ? (
                  <p className="text-sm text-muted-foreground">{t("deepLinkLoading")}</p>
                ) : linkPreview ? (
                  <>
                    <p className="text-sm">
                      <span className="text-muted-foreground">{t("deepLinkProposer")}</span>{" "}
                      {linkPreview.proposerFullName}
                    </p>
                    <p className="text-sm text-muted-foreground">
                      {linkPreview.templateName} · {linkPreview.locationName}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {new Date(linkPreview.scheduledStart).toLocaleString()} →{" "}
                      {new Date(linkPreview.scheduledEnd).toLocaleString()}
                    </p>
                    {linkPreview.stationLabel ? (
                      <p className="text-xs text-muted-foreground">
                        {linkPreview.stationLabel} · {t("slotShort", { index: linkPreview.slotIndex })}
                      </p>
                    ) : (
                      <p className="text-xs text-muted-foreground">
                        {t("slotShort", { index: linkPreview.slotIndex })}
                      </p>
                    )}
                    {myScheduled.length === 0 ? (
                      <p className="text-sm text-critical">{t("noScheduledForCounterparty")}</p>
                    ) : (
                      <>
                        <label className="block">
                          <span className="text-xs text-muted-foreground">{t("yourShiftToOffer")}</span>
                          <select
                            className="mt-1 w-full rounded-md border border-border bg-elevated px-3 py-2 text-sm"
                            value={counterpartyPickId}
                            onChange={(e) => setCounterpartyPickId(e.target.value)}
                          >
                            <option value="">{t("pickShiftPlaceholder")}</option>
                            {myScheduled.map((s) => (
                              <option key={s.id} value={s.id}>
                                {s.templateName} · {s.locationName} ·{" "}
                                {new Date(s.scheduledStart).toLocaleString(undefined, {
                                  month: "short",
                                  day: "numeric",
                                  hour: "2-digit",
                                  minute: "2-digit",
                                })}
                              </option>
                            ))}
                          </select>
                        </label>
                        <label className="block">
                          <span className="text-xs text-muted-foreground">{t("messageLabel")}</span>
                          <textarea
                            className="mt-1 w-full min-h-[56px] rounded-md border border-border bg-background px-3 py-2 text-sm"
                            value={message}
                            onChange={(e) => setMessage(e.target.value)}
                            maxLength={280}
                          />
                        </label>
                        <Button
                          size="block"
                          onClick={() => void handleCreateFromDeepLink()}
                          disabled={creating || !counterpartyPickId}
                        >
                          {creating ? t("submitting") : t("submitDeepLink")}
                        </Button>
                      </>
                    )}
                  </>
                ) : (
                  <p className="text-sm text-critical">{t("deepLinkInvalid")}</p>
                )}
              </CardContent>
            </Card>
          ) : null}

          {!deepLinkProposerShiftId ? (
            <Card className="mb-4">
              <CardHeader>
                <CardTitle className="text-base">{t("newRequest")}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {myScheduled.length === 0 ? (
                  <p className="text-sm text-muted-foreground">{t("noScheduled")}</p>
                ) : (
                  <>
                    <label className="block">
                      <span className="text-xs text-muted-foreground">{t("myShiftLabel")}</span>
                      <select
                        className="mt-1 w-full rounded-md border border-border bg-elevated px-3 py-2 text-sm"
                        value={proposerShiftId}
                        onChange={(e) => setProposerShiftId(e.target.value)}
                      >
                        {myScheduled.map((s) => (
                          <option key={s.id} value={s.id}>
                            {s.templateName} · {s.locationName} ·{" "}
                            {new Date(s.scheduledStart).toLocaleString(undefined, {
                              month: "short",
                              day: "numeric",
                              hour: "2-digit",
                              minute: "2-digit",
                            })}
                          </option>
                        ))}
                      </select>
                    </label>
                    <Button
                      type="button"
                      variant="secondary"
                      size="block"
                      className="text-sm"
                      onClick={() => void handleShareInvite()}
                      disabled={!proposerShiftId}
                    >
                      {t("shareInviteCta")}
                    </Button>
                    <p className="text-[11px] text-muted-foreground">{t("shareInviteHint")}</p>
                    <label className="block">
                      <span className="text-xs text-muted-foreground">{t("counterpartyShiftLabel")}</span>
                      <input
                        type="text"
                        autoComplete="off"
                        className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm font-mono"
                        value={counterpartyShiftId}
                        onChange={(e) => setCounterpartyShiftId(e.target.value)}
                        placeholder="00000000-0000-0000-0000-000000000000"
                      />
                    </label>
                    <p className="text-[11px] text-muted-foreground">{t("counterpartyShiftHint")}</p>
                    <label className="block">
                      <span className="text-xs text-muted-foreground">{t("messageLabel")}</span>
                      <textarea
                        className="mt-1 w-full min-h-[56px] rounded-md border border-border bg-background px-3 py-2 text-sm"
                        value={message}
                        onChange={(e) => setMessage(e.target.value)}
                        maxLength={280}
                      />
                    </label>
                    <Button
                      size="block"
                      onClick={() => void handleCreate()}
                      disabled={creating || !proposerShiftId}
                    >
                      {creating ? t("submitting") : t("submit")}
                    </Button>
                  </>
                )}
              </CardContent>
            </Card>
          ) : null}

          <section className="mb-4">
            <h2 className="text-sm font-medium mb-2">{t("incoming")}</h2>
            {incoming.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("emptyIncoming")}</p>
            ) : (
              <ul className="space-y-2">
                {incoming.map((row) => (
                  <li key={row.id}>
                    <Card>
                      <CardContent className="p-3 space-y-2">
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <p className="text-sm font-medium truncate">{row.proposerName}</p>
                            <p className="text-[11px] text-muted-foreground">
                              {t("rowHint", {
                                from: new Date(row.createdAt).toLocaleString(),
                                to: row.resolvedAt
                                  ? new Date(row.resolvedAt).toLocaleString()
                                  : "—",
                              })}
                            </p>
                            <p className="text-[11px] text-muted-foreground mt-1">
                              {t("shiftsPair", {
                                mine: shortId(row.counterpartyShiftId),
                                theirs: shortId(row.proposerShiftId),
                              })}
                            </p>
                            {row.message ? (
                              <p className="text-xs mt-1 text-foreground/90 whitespace-pre-wrap">
                                {row.message}
                              </p>
                            ) : null}
                          </div>
                          <span className="text-[10px] uppercase tracking-wide text-muted-foreground shrink-0">
                            {statusLabel(row.status)}
                          </span>
                        </div>
                        {row.status === "pending" ? (
                          <div className="flex gap-2">
                            <Button
                              size="sm"
                              variant="secondary"
                              className="flex-1"
                              disabled={actingId === row.id}
                              onClick={() => void handleDecline(row.id)}
                            >
                              {t("decline")}
                            </Button>
                            <Button
                              size="sm"
                              className="flex-1"
                              disabled={actingId === row.id}
                              onClick={() => void handleAccept(row.id)}
                            >
                              {t("accept")}
                            </Button>
                          </div>
                        ) : null}
                      </CardContent>
                    </Card>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section>
            <h2 className="text-sm font-medium mb-2">{t("outgoing")}</h2>
            {outgoing.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("emptyOutgoing")}</p>
            ) : (
              <ul className="space-y-2">
                {outgoing.map((row) => (
                  <li key={row.id}>
                    <Card>
                      <CardContent className="p-3 space-y-2">
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <p className="text-sm font-medium truncate">{row.counterpartyName}</p>
                            <p className="text-[11px] text-muted-foreground">
                              {t("rowHint", {
                                from: new Date(row.createdAt).toLocaleString(),
                                to: row.resolvedAt
                                  ? new Date(row.resolvedAt).toLocaleString()
                                  : "—",
                              })}
                            </p>
                            <p className="text-[11px] text-muted-foreground mt-1">
                              {t("shiftsPair", {
                                mine: shortId(row.proposerShiftId),
                                theirs: shortId(row.counterpartyShiftId),
                              })}
                            </p>
                            {row.message ? (
                              <p className="text-xs mt-1 text-foreground/90 whitespace-pre-wrap">
                                {row.message}
                              </p>
                            ) : null}
                          </div>
                          <span className="text-[10px] uppercase tracking-wide text-muted-foreground shrink-0">
                            {statusLabel(row.status)}
                          </span>
                        </div>
                        {row.status === "pending" && me && row.proposerUserId === me.id ? (
                          <Button
                            size="sm"
                            variant="secondary"
                            className="w-full"
                            disabled={actingId === row.id}
                            onClick={() => void handleCancel(row.id)}
                          >
                            {t("cancel")}
                          </Button>
                        ) : null}
                      </CardContent>
                    </Card>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </main>
  );
}
