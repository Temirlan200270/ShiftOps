"use client";

/**
 * Deep link: t.me/<bot>?start=swap_req_<proposer_shift_uuid>
 * Colleague opens bot → /start → WebApp button with ?swap_proposer_shift=...
 */

export function buildSwapInviteTelegramStartUrl(proposerShiftId: string): string | null {
  const raw = process.env.NEXT_PUBLIC_TG_BOT_USERNAME?.trim();
  if (!raw) {
    return null;
  }
  const bot = raw.startsWith("@") ? raw.slice(1) : raw;
  return `https://t.me/${bot}?start=swap_req_${proposerShiftId}`;
}

export async function shareSwapInviteUrl(url: string, title: string): Promise<boolean> {
  if (typeof navigator !== "undefined" && typeof navigator.share === "function") {
    try {
      await navigator.share({ title, url });
      return true;
    } catch {
      /* user cancelled or share failed */
    }
  }
  try {
    await navigator.clipboard.writeText(url);
    return true;
  } catch {
    return false;
  }
}
