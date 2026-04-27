"""Storage provider abstraction.

Two implementations:
- :class:`shiftops_api.infra.storage.telegram_storage.TelegramStorage` (MVP)
- :class:`shiftops_api.infra.storage.r2_storage.R2Storage` (V2)

Both speak the same `StorageProvider` Protocol so the rest of the app never
knows which one is wired up.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AttachmentRef:
    """Provider-agnostic handle to an uploaded blob.

    Only the fields relevant to the chosen provider are populated. A typical
    Telegram-stored attachment has ``provider == "telegram"`` and three TG
    fields; an R2 one has ``provider == "r2"`` and ``r2_object_key``.
    """

    provider: str
    mime: str = "image/jpeg"
    size_bytes: int = 0
    tg_file_id: str | None = None
    tg_file_unique_id: str | None = None
    tg_archive_chat_id: int | None = None
    tg_archive_message_id: int | None = None
    r2_object_key: str | None = None
    extra: dict[str, str] = field(default_factory=dict)


class UploadFailed(Exception):
    """Raised when the underlying provider could not store the file.

    Use-cases catch this and translate to a `Failure(DomainError("upload_failed"))`.
    """


class StorageProvider(Protocol):
    """The only interface application-layer code is allowed to depend on."""

    async def upload(self, file: bytes, mime: str, meta: dict[str, str]) -> AttachmentRef:
        """Upload bytes and return a reference suitable for persistence."""

    async def get_url(
        self,
        ref: AttachmentRef,
        ttl_seconds: int = 3600,
    ) -> str:
        """Return a temporary URL the client can fetch the blob from.

        Implementations may refresh stale references (e.g. Telegram's
        forward_message fallback) and may return a URL valid for less than
        ``ttl_seconds``.
        """
