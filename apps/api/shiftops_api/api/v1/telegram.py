"""Telegram webhook endpoint.

We register a single webhook with Telegram pointing to this path. The handler
verifies the secret header and dispatches to aiogram's `Dispatcher`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from shiftops_api.config import get_settings
from shiftops_api.infra.telegram.bot import dispatch_update

router = APIRouter()


def _verify_secret(
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> None:
    expected = get_settings().tg_webhook_secret.get_secret_value()
    if not expected or x_telegram_bot_api_secret_token != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid telegram webhook secret",
        )


@router.post("/webhook", dependencies=[Depends(_verify_secret)])
async def webhook(request: Request) -> dict[str, str]:
    payload = await request.json()
    await dispatch_update(payload)
    return {"status": "ok"}
