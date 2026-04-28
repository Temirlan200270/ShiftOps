"use client";

import { api } from "@/lib/api/client";
import { useAuthStore, type MeProfile } from "@/lib/stores/auth-store";
import { getInitDataRaw } from "@/lib/telegram/init";

/**
 * Performs the Telegram initData → JWT exchange and writes the session into
 * the auth store. Resolves with the resulting `MeProfile` or throws an
 * error with a stable code that the splash screen can map to copy.
 *
 * Wire format mirrors `apps/api/shiftops_api/api/v1/auth.py:TelegramAuthResponse`.
 * If you rename a field there, rename it here in the same commit.
 */

interface ExchangeResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  me: {
    id: string;
    full_name: string;
    role: MeProfile["role"];
    organization_id: string;
    locale: MeProfile["locale"];
    tg_user_id: number | null;
  };
}

export class HandshakeError extends Error {
  public readonly code: string;
  public constructor(code: string, message: string) {
    super(message);
    this.code = code;
    this.name = "HandshakeError";
  }
}

let handshakeFlight: Promise<MeProfile> | null = null;

export async function performHandshake(): Promise<MeProfile> {
  if (handshakeFlight) {
    return handshakeFlight;
  }
  handshakeFlight = (async (): Promise<MeProfile> => {
    const initData = getInitDataRaw();
    if (!initData) {
      throw new HandshakeError("not_in_telegram", "initData not present");
    }

    const result = await api.post<ExchangeResponse>("/v1/auth/exchange", { init_data: initData });
    if (!result.ok) {
      throw new HandshakeError(result.code || "exchange_failed", result.message);
    }

    const { access_token, refresh_token, me } = result.data;
    const profile: MeProfile = {
      id: me.id,
      fullName: me.full_name,
      role: me.role,
      organizationId: me.organization_id,
      locale: me.locale,
      tgUserId: me.tg_user_id,
    };
    useAuthStore.getState().setSession({
      accessToken: access_token,
      refreshToken: refresh_token,
      me: profile,
    });
    return profile;
  })().finally(() => {
    handshakeFlight = null;
  });
  return handshakeFlight;
}


