"""Use-case: operator marks a task complete (with optional photo).

Combines:
- task transition pending -> done (or rejection if photo missing on a
  requires_photo task);
- anti-fake pipeline (server timestamp + perceptual hash);
- attachment persistence;
- audit-log entry;
- background notification to admin group on suspicious / critical events.
"""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.audit import write_audit
from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.domain.enums import (
    CaptureMethod,
    Criticality,
    ShiftStatus,
    StorageKind,
    TaskStatus,
    UserRole,
)
from shiftops_api.domain.result import DomainError, Failure, Result, Success
from shiftops_api.infra.antifake.phash import compute_phash, find_similar
from shiftops_api.infra.db.models import (
    Attachment,
    Shift,
    TaskInstance,
    TemplateTask,
)
from shiftops_api.infra.metrics import ATTACHMENTS_UPLOADED_TOTAL
from shiftops_api.infra.storage.interface import StorageProvider, UploadFailed


@dataclass(frozen=True, slots=True)
class CompletedTask:
    status: str
    suspicious: bool


class CompleteTaskUseCase:
    def __init__(
        self,
        *,
        session: AsyncSession,
        storage: StorageProvider,
        phash_threshold: int = 5,
        history_lookback: int = 50,
    ) -> None:
        self._session = session
        self._storage = storage
        self._phash_threshold = phash_threshold
        self._history_lookback = history_lookback

    async def execute(
        self,
        *,
        task_id: uuid.UUID,
        user: CurrentUser,
        photo_bytes: bytes | None,
        photo_mime: str | None,
        comment: str | None,
    ) -> Result[CompletedTask, DomainError]:
        row = (
            await self._session.execute(
                select(TaskInstance, TemplateTask, Shift)
                .join(TemplateTask, TemplateTask.id == TaskInstance.template_task_id)
                .join(Shift, Shift.id == TaskInstance.shift_id)
                .where(TaskInstance.id == task_id)
            )
        ).first()
        if row is None:
            return Failure(DomainError("task_not_found"))

        task, template_task, shift = row

        if user.role == UserRole.OPERATOR and shift.operator_user_id != user.id:
            return Failure(DomainError("not_your_shift"))

        if shift.status != ShiftStatus.ACTIVE:
            return Failure(DomainError("shift_not_active"))

        if task.status not in (TaskStatus.PENDING, TaskStatus.WAIVER_REJECTED):
            return Failure(DomainError("task_not_in_pending_state"))

        if template_task.requires_photo and not photo_bytes:
            return Failure(DomainError("photo_required"))

        if template_task.requires_comment and not comment:
            return Failure(DomainError("comment_required"))

        suspicious = False

        if photo_bytes is not None:
            phash_hex = compute_phash(photo_bytes)
            similar = await find_similar(
                session=self._session,
                template_task_id=template_task.id,
                location_id=shift.location_id,
                phash_hex=phash_hex,
                threshold=self._phash_threshold,
                lookback=self._history_lookback,
            )
            suspicious = similar is not None

            try:
                ref = await self._storage.upload(
                    file=photo_bytes,
                    mime=photo_mime or "image/jpeg",
                    meta={
                        "caption": (
                            f"shift={shift.id} task={task.id} "
                            f"by={user.id} suspicious={'yes' if suspicious else 'no'}"
                        ),
                    },
                )
            except UploadFailed as exc:
                return Failure(DomainError("upload_failed", message=str(exc)))

            attachment = Attachment(
                task_instance_id=task.id,
                storage_provider=ref.provider,
                tg_file_id=ref.tg_file_id,
                tg_file_unique_id=ref.tg_file_unique_id,
                tg_archive_chat_id=ref.tg_archive_chat_id,
                tg_archive_message_id=ref.tg_archive_message_id,
                r2_object_key=ref.r2_object_key,
                mime=ref.mime,
                size_bytes=ref.size_bytes,
                phash=phash_hex,
                suspicious=suspicious,
                capture_method=CaptureMethod.CAMERA.value,
                captured_at_server=datetime.now(tz=timezone.utc),
            )
            self._session.add(attachment)

            ATTACHMENTS_UPLOADED_TOTAL.labels(
                provider=str(ref.provider),
                suspicious="yes" if suspicious else "no",
            ).inc()

        task.status = TaskStatus.DONE.value
        task.completed_at = datetime.now(tz=timezone.utc)
        if comment:
            task.comment = comment

        await write_audit(
            session=self._session,
            organization_id=user.organization_id,
            actor_user_id=user.id,
            event_type="task.completed",
            payload={
                "task_id": str(task.id),
                "shift_id": str(shift.id),
                "criticality": template_task.criticality,
                "with_photo": photo_bytes is not None,
                "suspicious": suspicious,
            },
        )
        await self._session.commit()

        from shiftops_api.infra.notifications.dispatcher import (
            dispatch_suspicious_photo_alert,
            dispatch_task_progress,
        )

        if suspicious:
            await dispatch_suspicious_photo_alert(
                shift_id=shift.id,
                task_id=task.id,
                actor_user_id=user.id,
            )

        # Live-monitor event. This goes onto the realtime bus only —
        # Telegram still batches at close time per TELEGRAM_BOT.md so we
        # don't spam admin chats.
        await dispatch_task_progress(
            shift_id=shift.id,
            task_id=task.id,
            actor_user_id=user.id,
            new_status=TaskStatus.DONE.value,
            suspicious=suspicious,
        )

        _ = template_task.criticality is Criticality.CRITICAL  # placeholder for V1
        _ = io  # silence unused-import linter for v0 (reserved for future stream API)

        return Success(CompletedTask(status=TaskStatus.DONE.value, suspicious=suspicious))
