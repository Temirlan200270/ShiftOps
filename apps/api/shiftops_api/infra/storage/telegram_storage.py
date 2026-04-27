"""Telegram-as-storage implementation of `StorageProvider`.

The contract:

- :meth:`upload` posts the photo to a private archive chat owned by the bot
  and returns a reference containing the resulting ``file_id``,
  ``file_unique_id``, ``chat_id`` and ``message_id``. The latter two let us
  refresh the file via ``forward_message`` if the file_id ever expires.

- :meth:`get_url` calls ``getFile``. On 400 ("file is too old") it forwards
  the archived message to refresh the file_id, then retries.

Notes:
- Network calls use ``httpx`` directly against the Bot API rather than
  routing through the running aiogram dispatcher; this keeps the storage
  layer independent of the bot lifecycle.
- We never store the bot token in returned references — only opaque IDs.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from shiftops_api.config import get_settings

from .interface import AttachmentRef, StorageProvider, UploadFailed


_log = logging.getLogger(__name__)
_TG_API = "https://api.telegram.org"


class TelegramStorage(StorageProvider):
    def __init__(
        self,
        *,
        bot_token: str | None = None,
        archive_chat_id: int | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        settings = get_settings()
        self._token = bot_token or settings.tg_bot_token.get_secret_value()
        self._archive_chat_id = archive_chat_id or settings.tg_archive_chat_id
        if not self._token:
            raise UploadFailed("TG_BOT_TOKEN is not configured")
        if not self._archive_chat_id:
            raise UploadFailed("TG_ARCHIVE_CHAT_ID is not configured")
        self._client = client or httpx.AsyncClient(timeout=30.0)

    @property
    def _base(self) -> str:
        return f"{_TG_API}/bot{self._token}"

    @property
    def _file_base(self) -> str:
        return f"{_TG_API}/file/bot{self._token}"

    async def upload(self, file: bytes, mime: str, meta: dict[str, str]) -> AttachmentRef:
        caption = meta.get("caption", "")
        files = {"photo": ("upload.jpg", file, mime)}
        data: dict[str, Any] = {"chat_id": self._archive_chat_id, "caption": caption}
        try:
            resp = await self._client.post(f"{self._base}/sendPhoto", data=data, files=files)
        except httpx.HTTPError as exc:
            raise UploadFailed(f"telegram_send_photo_network: {exc}") from exc

        body = resp.json()
        if not body.get("ok"):
            raise UploadFailed(f"telegram_send_photo: {body!r}")

        message = body["result"]
        photos = message["photo"]
        # Telegram returns multiple sizes; pick the largest.
        biggest = max(photos, key=lambda p: int(p.get("file_size", 0)))
        return AttachmentRef(
            provider="telegram",
            mime=mime,
            size_bytes=int(biggest.get("file_size", len(file))),
            tg_file_id=biggest["file_id"],
            tg_file_unique_id=biggest["file_unique_id"],
            tg_archive_chat_id=int(message["chat"]["id"]),
            tg_archive_message_id=int(message["message_id"]),
        )

    async def get_url(
        self,
        ref: AttachmentRef,
        ttl_seconds: int = 3600,
    ) -> str:
        if ref.provider != "telegram":
            raise UploadFailed(f"wrong provider: {ref.provider}")
        url, _refreshed_ref = await self.get_url_with_refresh(ref)
        return url

    async def get_url_with_refresh(
        self, ref: AttachmentRef
    ) -> tuple[str, AttachmentRef]:
        """Return (url, possibly_refreshed_ref).

        The caller is expected to persist the refreshed ref if it differs from
        the input — saves a forward on the next view.
        """
        url = await self._try_get_file(ref.tg_file_id)
        if url is not None:
            return url, ref

        if ref.tg_archive_chat_id is None or ref.tg_archive_message_id is None:
            raise UploadFailed("file_id_expired_no_archive")

        _log.info(
            "telegram_storage.refresh_via_forward",
            extra={"chat": ref.tg_archive_chat_id, "msg": ref.tg_archive_message_id},
        )
        forwarded = await self._forward_archive(
            chat_id=ref.tg_archive_chat_id,
            message_id=ref.tg_archive_message_id,
        )
        photos = forwarded["photo"]
        biggest = max(photos, key=lambda p: int(p.get("file_size", 0)))
        new_ref = AttachmentRef(
            provider="telegram",
            mime=ref.mime,
            size_bytes=int(biggest.get("file_size", ref.size_bytes)),
            tg_file_id=biggest["file_id"],
            tg_file_unique_id=biggest["file_unique_id"],
            tg_archive_chat_id=int(forwarded["chat"]["id"]),
            tg_archive_message_id=int(forwarded["message_id"]),
        )
        url = await self._try_get_file(new_ref.tg_file_id)
        if url is None:
            raise UploadFailed("forward_succeeded_but_get_file_failed")
        return url, new_ref

    async def _try_get_file(self, file_id: str | None) -> str | None:
        if not file_id:
            return None
        try:
            resp = await self._client.get(
                f"{self._base}/getFile",
                params={"file_id": file_id},
            )
        except httpx.HTTPError:
            return None
        body = resp.json()
        if not body.get("ok"):
            return None
        file_path = body["result"].get("file_path")
        if not file_path:
            return None
        return f"{self._file_base}/{file_path}"

    async def _forward_archive(self, *, chat_id: int, message_id: int) -> dict[str, Any]:
        try:
            resp = await self._client.post(
                f"{self._base}/forwardMessage",
                data={
                    "chat_id": chat_id,
                    "from_chat_id": chat_id,
                    "message_id": message_id,
                },
            )
        except httpx.HTTPError as exc:
            raise UploadFailed(f"forward_network: {exc}") from exc
        body = resp.json()
        if not body.get("ok"):
            raise UploadFailed(f"forward_failed: {body!r}")
        return body["result"]

    async def aclose(self) -> None:
        await self._client.aclose()
