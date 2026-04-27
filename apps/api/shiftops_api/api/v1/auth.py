"""Auth router — Telegram initData -> JWT exchange.

Implementation lives in the application/auth and infra/telegram modules.
This file just wires HTTP.

Path & response shape are stable contracts consumed by:
  - apps/web/lib/auth/handshake.ts   (frontend)
  - apps/api/scripts/smoke_pilot.py  (E2E test)
Do NOT rename without updating both clients in the same commit.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.auth.exchange_init_data import (
    AuthFailure,
    AuthSuccess,
    ExchangeInitDataUseCase,
)
from shiftops_api.config import get_settings
from shiftops_api.infra.db.engine import get_session
from shiftops_api.infra.telegram.init_data import InitDataValidator

router = APIRouter()


class TelegramAuthRequest(BaseModel):
    init_data: str


class MeProfile(BaseModel):
    id: str
    full_name: str
    role: str
    organization_id: str
    locale: str | None = None
    tg_user_id: int | None = None


class TelegramAuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int
    me: MeProfile


@router.post(
    "/exchange",
    response_model=TelegramAuthResponse,
    summary="Exchange Telegram initData for a JWT pair",
)
async def telegram_exchange(
    payload: TelegramAuthRequest,
    session: AsyncSession = Depends(get_session),
) -> TelegramAuthResponse:
    settings = get_settings()
    if not settings.tg_bot_token.get_secret_value():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="telegram_not_configured",
        )

    use_case = ExchangeInitDataUseCase(
        validator=InitDataValidator(bot_token=settings.tg_bot_token.get_secret_value()),
        session=session,
    )
    result = await use_case.execute(payload.init_data)
    if isinstance(result, AuthFailure):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=result.reason)

    assert isinstance(result, AuthSuccess)
    return TelegramAuthResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=settings.jwt_access_ttl_seconds,
        me=MeProfile(
            id=str(result.user.id),
            full_name=result.user.full_name,
            role=result.user.role.value,
            organization_id=str(result.user.organization_id),
            locale=result.user.locale,
            tg_user_id=result.user.tg_user_id,
        ),
    )
