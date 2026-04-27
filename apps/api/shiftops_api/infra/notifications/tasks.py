"""TaskIQ tasks for Telegram outbound traffic.

Two reasons to use a queue (instead of awaiting in the request handler):

1. **Latency:** the operator should not wait for an admin chat post to render
   their next screen.
2. **Rate limit / backpressure:** Telegram returns 429 with `retry_after`
   under load. Retrying inline blocks the request thread; the queue retries
   with backoff.

Tasks here are deliberately small and idempotent. State (e.g. "did we
already post this shift_closed message?") is delegated to the use-cases.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx
from taskiq import TaskiqDepends

from shiftops_api.config import get_settings
from shiftops_api.infra.metrics import (
    TELEGRAM_SEND_DURATION_SECONDS,
    TELEGRAM_SEND_TOTAL,
)
from shiftops_api.infra.queue import broker

from .rate_limit import TelegramChatRateLimiter


_log = logging.getLogger(__name__)
_TG_API = "https://api.telegram.org"


async def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=30.0)


def _bot_url(method: str) -> str:
    token = get_settings().tg_bot_token.get_secret_value()
    return f"{_TG_API}/bot{token}/{method}"


@broker.task(retry_on_error=True, max_retries=5, delay=2)
async def send_telegram_message(
    chat_id: int,
    text: str,
    *,
    parse_mode: str | None = "HTML",
    reply_markup: dict[str, Any] | None = None,
    limiter: TelegramChatRateLimiter = TaskiqDepends(TelegramChatRateLimiter),
) -> None:
    take = await limiter.take(chat_id)
    if not take.allowed:
        await asyncio.sleep(min(2.0, take.retry_after_seconds))

    payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = reply_markup

    started = time.perf_counter()
    result_label = "ok"
    try:
        async with await _client() as client:
            resp = await client.post(_bot_url("sendMessage"), json=payload)

        if resp.status_code == 429:
            retry_after = float(resp.json().get("parameters", {}).get("retry_after", 1))
            _log.warning("tg.send_message.429", extra={"chat_id": chat_id, "retry": retry_after})
            await asyncio.sleep(retry_after)
            result_label = "rate_limited"
            raise RuntimeError("tg_rate_limited_retry")

        if not resp.json().get("ok"):
            result_label = "error"
            _log.error("tg.send_message.failed", extra={"chat_id": chat_id, "body": resp.text})
    except Exception:
        # Anything that escapes the tracked branches above counts as an
        # error from the caller's POV (TaskIQ will retry, our metric
        # rolls up that retry).
        if result_label == "ok":
            result_label = "error"
        raise
    finally:
        TELEGRAM_SEND_TOTAL.labels(method="sendMessage", result=result_label).inc()
        TELEGRAM_SEND_DURATION_SECONDS.labels(method="sendMessage").observe(
            time.perf_counter() - started
        )


@broker.task(retry_on_error=True, max_retries=5, delay=2)
async def send_telegram_media_group(
    chat_id: int,
    media: list[dict[str, str]],
    *,
    limiter: TelegramChatRateLimiter = TaskiqDepends(TelegramChatRateLimiter),
) -> None:
    """Send up to 10 media items as a single album.

    `media` is a list of `{"type": "photo", "media": "<file_id>", "caption": "..."}`.
    """
    if not media:
        return
    if len(media) > 10:
        raise ValueError("media group max size is 10")

    take = await limiter.take(chat_id)
    if not take.allowed:
        await asyncio.sleep(min(2.0, take.retry_after_seconds))

    started = time.perf_counter()
    result_label = "ok"
    try:
        async with await _client() as client:
            resp = await client.post(
                _bot_url("sendMediaGroup"),
                json={"chat_id": chat_id, "media": media},
            )

        if resp.status_code == 429:
            retry_after = float(resp.json().get("parameters", {}).get("retry_after", 1))
            await asyncio.sleep(retry_after)
            result_label = "rate_limited"
            raise RuntimeError("tg_rate_limited_retry")

        if not resp.json().get("ok"):
            result_label = "error"
            _log.error(
                "tg.send_media_group.failed", extra={"chat_id": chat_id, "body": resp.text}
            )
    except Exception:
        if result_label == "ok":
            result_label = "error"
        raise
    finally:
        TELEGRAM_SEND_TOTAL.labels(method="sendMediaGroup", result=result_label).inc()
        TELEGRAM_SEND_DURATION_SECONDS.labels(method="sendMediaGroup").observe(
            time.perf_counter() - started
        )


@broker.task
async def send_telegram_photo(
    chat_id: int,
    file_id: str,
    *,
    caption: str | None = None,
    reply_markup: dict[str, Any] | None = None,
    limiter: TelegramChatRateLimiter = TaskiqDepends(TelegramChatRateLimiter),
) -> None:
    take = await limiter.take(chat_id)
    if not take.allowed:
        await asyncio.sleep(min(2.0, take.retry_after_seconds))

    payload: dict[str, Any] = {"chat_id": chat_id, "photo": file_id}
    if caption:
        payload["caption"] = caption
    if reply_markup:
        payload["reply_markup"] = reply_markup

    started = time.perf_counter()
    result_label = "ok"
    try:
        async with await _client() as client:
            resp = await client.post(_bot_url("sendPhoto"), json=payload)

        if not resp.json().get("ok"):
            result_label = "error"
            _log.error("tg.send_photo.failed", extra={"chat_id": chat_id, "body": resp.text})
    except Exception:
        if result_label == "ok":
            result_label = "error"
        raise
    finally:
        TELEGRAM_SEND_TOTAL.labels(method="sendPhoto", result=result_label).inc()
        TELEGRAM_SEND_DURATION_SECONDS.labels(method="sendPhoto").observe(
            time.perf_counter() - started
        )
