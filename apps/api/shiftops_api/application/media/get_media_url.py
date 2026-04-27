"""Use-case: produce a temporary URL for an attachment, refreshing if needed.

The proxy endpoint is the only entry point through which the FE views photos.
RLS on `attachments` already guarantees a tenant cannot see another tenant's
rows; this use-case adds an extra explicit ownership check (defence in
depth — RLS is great, but explicit is friendlier in logs).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.domain.enums import StorageKind
from shiftops_api.infra.db.models import Attachment, Shift, TaskInstance
from shiftops_api.infra.storage.interface import AttachmentRef, StorageProvider
from shiftops_api.infra.storage.telegram_storage import TelegramStorage


class GetMediaUrlUseCase:
    def __init__(self, *, session: AsyncSession, storage: StorageProvider) -> None:
        self._session = session
        self._storage = storage

    async def execute(
        self,
        *,
        attachment_id: uuid.UUID,
        user: CurrentUser,
    ) -> str | None:
        # Single query: load attachment + parent shift in one go to verify
        # ownership without a second round trip.
        stmt = (
            select(Attachment, Shift)
            .join(TaskInstance, TaskInstance.id == Attachment.task_instance_id)
            .join(Shift, Shift.id == TaskInstance.shift_id)
            .where(Attachment.id == attachment_id)
        )
        row = (await self._session.execute(stmt)).first()
        if row is None:
            return None  # 404 — RLS already filtered cross-org rows

        attachment, shift = row
        if shift.organization_id != user.organization_id:
            return None  # Belt-and-braces: RLS should prevent this branch.

        ref = AttachmentRef(
            provider=attachment.storage_provider,
            mime=attachment.mime,
            size_bytes=attachment.size_bytes,
            tg_file_id=attachment.tg_file_id,
            tg_file_unique_id=attachment.tg_file_unique_id,
            tg_archive_chat_id=attachment.tg_archive_chat_id,
            tg_archive_message_id=attachment.tg_archive_message_id,
            r2_object_key=attachment.r2_object_key,
        )

        # Telegram-specific: if the storage refreshed the ref via forward,
        # persist the new file_id so the next view skips the round trip.
        if isinstance(self._storage, TelegramStorage) and attachment.storage_provider == StorageKind.TELEGRAM:
            url, refreshed = await self._storage.get_url_with_refresh(ref)
            if refreshed.tg_file_id != ref.tg_file_id:
                attachment.tg_file_id = refreshed.tg_file_id
                attachment.tg_file_unique_id = refreshed.tg_file_unique_id
                attachment.tg_archive_message_id = refreshed.tg_archive_message_id
                await self._session.commit()
            return url

        return await self._storage.get_url(ref)
