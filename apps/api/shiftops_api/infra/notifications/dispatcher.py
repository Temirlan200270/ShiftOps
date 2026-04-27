"""High-level notification dispatchers.

Use-cases call functions here (`dispatch_shift_opened`, ...) which look up the
right chat IDs (admin group, owner DM, operator DM) and enqueue per-chat
Telegram tasks.

Why dispatchers and not direct task calls in use-cases:

- Use-cases stay UI-/transport-agnostic and only know "an interesting thing
  happened".
- The dispatcher is the only place that knows the notification matrix
  documented in `docs/TELEGRAM_BOT.md`. If the matrix changes, only this file
  changes.

For V0 we keep things simple: dispatchers are async functions that compose
copy strings and enqueue `send_telegram_message`. Localisation per recipient
is V1 work — current copy is RU because the pilot is Russian-speaking.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.infra.db.engine import get_sessionmaker
from shiftops_api.infra.db.models import (
    Attachment,
    Location,
    Shift,
    TaskInstance,
    TelegramAccount,
    Template,
    TemplateTask,
    User,
)
from shiftops_api.infra.metrics import (
    ATTACHMENT_PHASH_COLLISIONS_TOTAL,
    SHIFTS_CLOSED_TOTAL,
    SHIFTS_STARTED_TOTAL,
    TASKS_COMPLETED_TOTAL,
    VIOLATION_TYPE_INCOMPLETE_REQUIRED,
    VIOLATION_TYPE_LATE_CLOSE,
    VIOLATION_TYPE_PHASH_COLLISION,
    VIOLATIONS_TOTAL,
    WAIVER_DECISIONS_TOTAL,
    WAIVER_REQUESTS_TOTAL,
    WAIVER_STATUS_APPROVED,
    WAIVER_STATUS_OPEN,
    WAIVER_STATUS_REJECTED,
)
from shiftops_api.infra.notifications.tasks import (
    send_telegram_media_group,
    send_telegram_message,
)
from shiftops_api.infra.realtime import publish_event

_log = logging.getLogger(__name__)


def _open_session() -> AsyncSession:
    """Open an unmanaged session — caller is responsible for `await session.close()`.

    Notifications run *outside* a per-request RLS-enforcing transaction (they
    are dispatched from use-cases that have already committed). We therefore
    operate with the privileged service role; tenant isolation is preserved
    by always filtering by `organization_id` derived from the entity itself.
    """
    factory = get_sessionmaker()
    return factory()


async def _resolve_admin_chat_id(session: AsyncSession, location_id: uuid.UUID) -> int | None:
    location = (
        await session.execute(select(Location).where(Location.id == location_id))
    ).scalar_one_or_none()
    return location.tg_admin_chat_id if location else None


async def _resolve_owner_dm_ids(session: AsyncSession, organization_id: uuid.UUID) -> list[int]:
    stmt = (
        select(TelegramAccount.tg_user_id)
        .join(User, User.id == TelegramAccount.user_id)
        .where(User.organization_id == organization_id)
        .where(User.role == "owner")
        .where(User.is_active.is_(True))
    )
    return [row for row in (await session.execute(stmt)).scalars().all() if row]


async def _resolve_operator_dm_id(session: AsyncSession, user_id: uuid.UUID) -> int | None:
    return (
        await session.execute(
            select(TelegramAccount.tg_user_id).where(TelegramAccount.user_id == user_id)
        )
    ).scalar_one_or_none()


# Anything past this many seconds beyond `scheduled_end` is recorded as
# a `late_close` violation. 15 minutes mirrors the same threshold the
# score formula uses for the timeliness penalty (`docs/SCORE_FORMULA.md`).
_LATE_CLOSE_TOLERANCE_SECONDS: int = 15 * 60


async def _emit_violation_metrics(
    *,
    session: AsyncSession,
    shift: Shift,
    location_id: str,
) -> None:
    """Increment ``shiftops_violations_total`` for each rule a shift broke.

    Called from ``dispatch_shift_closed`` after the close has already
    committed. Reads from the same session that fetched the shift, so
    no extra round-trip to the application use-case is needed.

    Violation taxonomy:

    - ``incomplete_required`` — one count per ``skipped`` required task.
    - ``late_close`` — fired once if the shift closed > 15 min past
      its scheduled end. The score formula already penalises this; the
      counter exists so dashboards can show the *frequency* of late
      closes (which the score doesn't surface).
    - ``phash_collision`` — handled in ``dispatch_task_progress``;
      not duplicated here.
    """

    # `skipped` is the status the close use-case writes for missed
    # required tasks (`application/shifts/close_shift.py`). Counting
    # rows is cheaper than re-loading them through the ORM.
    skipped_count = (
        await session.execute(
            select(func.count(TaskInstance.id))
            .where(TaskInstance.shift_id == shift.id)
            .where(TaskInstance.status == "skipped")
        )
    ).scalar_one()
    if skipped_count:
        VIOLATIONS_TOTAL.labels(
            type=VIOLATION_TYPE_INCOMPLETE_REQUIRED,
            location_id=location_id,
        ).inc(int(skipped_count))

    if shift.actual_end and shift.scheduled_end:
        overshoot = (shift.actual_end - shift.scheduled_end).total_seconds()
        if overshoot > _LATE_CLOSE_TOLERANCE_SECONDS:
            VIOLATIONS_TOTAL.labels(
                type=VIOLATION_TYPE_LATE_CLOSE,
                location_id=location_id,
            ).inc()


async def dispatch_shift_opened(*, shift_id: uuid.UUID) -> None:
    session = _open_session()
    try:
        row = (
            await session.execute(
                select(Shift, Location, Template, User)
                .join(Location, Location.id == Shift.location_id)
                .join(Template, Template.id == Shift.template_id)
                .join(User, User.id == Shift.operator_user_id)
                .where(Shift.id == shift_id)
            )
        ).first()
        if row is None:
            return
        shift, location, template, operator = row
        text = (
            f"🟢 [{location.name}] {operator.full_name} начал «{template.name}» в "
            f"{shift.actual_start.strftime('%H:%M') if shift.actual_start else '?'}"
        )
        admin_chat_id = location.tg_admin_chat_id
        owner_chats = await _resolve_owner_dm_ids(session, shift.organization_id)
        if admin_chat_id:
            await send_telegram_message.kiq(admin_chat_id, text)
        for owner_chat in owner_chats:
            await send_telegram_message.kiq(owner_chat, text)

        await publish_event(
            organization_id=shift.organization_id,
            event_type="shift.opened",
            data={
                "shift_id": str(shift.id),
                "location_id": str(location.id),
                "location_name": location.name,
                "template_id": str(template.id),
                "template_name": template.name,
                "operator_id": str(operator.id),
                "operator_name": operator.full_name,
                "scheduled_start": shift.scheduled_start.isoformat(),
                "scheduled_end": shift.scheduled_end.isoformat(),
                "actual_start": (
                    shift.actual_start.isoformat() if shift.actual_start else None
                ),
            },
        )

        SHIFTS_STARTED_TOTAL.labels(
            location_id=str(location.id),
            template_id=str(template.id),
        ).inc()
    finally:
        await session.close()


async def dispatch_task_progress(
    *,
    shift_id: uuid.UUID,
    task_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    new_status: str,
    suspicious: bool = False,
) -> None:
    """Publish a real-time progress event for the admin live monitor.

    Telegram is intentionally *not* notified per task — that's the
    `dispatch_shift_closed` media-group strategy. The realtime bus is
    cheaper than a TG message and can carry the per-task firehose
    without spamming any chats.
    """
    session = _open_session()
    try:
        row = (
            await session.execute(
                select(Shift, Location, TemplateTask, TaskInstance)
                .join(Location, Location.id == Shift.location_id)
                .join(TaskInstance, TaskInstance.id == task_id)
                .join(TemplateTask, TemplateTask.id == TaskInstance.template_task_id)
                .where(Shift.id == shift_id)
            )
        ).first()
        if row is None:
            return
        shift, location, template_task, task_instance = row

        # Compute live progress so the admin UI can render the same
        # progress bar the operator sees, without a follow-up GET.
        progress_row = (
            await session.execute(
                select(
                    func.count(TaskInstance.id).label("total"),
                    func.count(TaskInstance.id)
                    .filter(TaskInstance.status.in_(["done", "waived"]))
                    .label("done"),
                ).where(TaskInstance.shift_id == shift_id)
            )
        ).one()

        await publish_event(
            organization_id=shift.organization_id,
            event_type="task.completed",
            data={
                "shift_id": str(shift.id),
                "task_id": str(task_id),
                "location_name": location.name,
                "template_task_title": template_task.title,
                "criticality": template_task.criticality,
                "status": new_status,
                "suspicious": suspicious,
                "progress_total": int(progress_row.total or 0),
                "progress_done": int(progress_row.done or 0),
            },
        )

        # Only count terminal "done" transitions toward tasks_completed.
        # `waived` flows through this dispatcher too (status=waived) and
        # should not inflate the task-completion rate dashboards.
        if new_status == "done":
            TASKS_COMPLETED_TOTAL.labels(criticality=str(template_task.criticality)).inc()
            if suspicious:
                # Two related metrics: the standalone counter for
                # quick "anti-fake heat" panels, and a violations row
                # so the violations dashboard captures the same event
                # under the unified rule-break taxonomy.
                ATTACHMENT_PHASH_COLLISIONS_TOTAL.inc()
                VIOLATIONS_TOTAL.labels(
                    type=VIOLATION_TYPE_PHASH_COLLISION,
                    location_id=str(location.id),
                ).inc()

        _ = actor_user_id  # currently unused but reserved for "by whom" UI
        _ = task_instance
    finally:
        await session.close()


async def dispatch_suspicious_photo_alert(
    *,
    shift_id: uuid.UUID,
    task_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> None:
    session = _open_session()
    try:
        row = (
            await session.execute(
                select(Shift, Location, TemplateTask, User)
                .join(Location, Location.id == Shift.location_id)
                .join(TaskInstance, TaskInstance.id == task_id)
                .join(TemplateTask, TemplateTask.id == TaskInstance.template_task_id)
                .join(User, User.id == actor_user_id)
                .where(Shift.id == shift_id)
            )
        ).first()
        if row is None:
            return
        shift, location, template_task, actor = row
        text = (
            f"⚠️ [{location.name}] подозрительное фото на задаче «{template_task.title}» — "
            f"{actor.full_name}.\n"
            f"Откройте отчёт смены, чтобы сравнить с предыдущим."
        )
        admin_chat_id = location.tg_admin_chat_id
        if admin_chat_id:
            await send_telegram_message.kiq(admin_chat_id, text)
        for owner_chat in await _resolve_owner_dm_ids(session, shift.organization_id):
            await send_telegram_message.kiq(owner_chat, text)

        await publish_event(
            organization_id=shift.organization_id,
            event_type="task.suspicious",
            data={
                "shift_id": str(shift.id),
                "task_id": str(task_id),
                "location_name": location.name,
                "template_task_title": template_task.title,
                "operator_name": actor.full_name,
            },
        )
    finally:
        await session.close()


async def dispatch_waiver_request(
    *,
    task_id: uuid.UUID,
    shift_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    reason: str,
) -> None:
    session = _open_session()
    try:
        row = (
            await session.execute(
                select(Shift, Location, TemplateTask, User)
                .join(Location, Location.id == Shift.location_id)
                .join(TaskInstance, TaskInstance.id == task_id)
                .join(TemplateTask, TemplateTask.id == TaskInstance.template_task_id)
                .join(User, User.id == actor_user_id)
                .where(Shift.id == shift_id)
            )
        ).first()
        if row is None:
            return
        shift, location, template_task, actor = row
        text = (
            f"🛑 [{location.name}] {actor.full_name} просит waive задачу "
            f"«{template_task.title}» (причина: {reason}).\n"
            "У вас 5 минут, чтобы решить."
        )
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "✅ Approve", "callback_data": f"waiver:{task_id}:approve"},
                    {"text": "❌ Reject", "callback_data": f"waiver:{task_id}:reject"},
                ]
            ]
        }
        admin_chat_id = location.tg_admin_chat_id
        if admin_chat_id:
            await send_telegram_message.kiq(admin_chat_id, text, reply_markup=keyboard)
        for owner_chat in await _resolve_owner_dm_ids(session, shift.organization_id):
            await send_telegram_message.kiq(owner_chat, text, reply_markup=keyboard)

        await publish_event(
            organization_id=shift.organization_id,
            event_type="waiver.requested",
            data={
                "shift_id": str(shift.id),
                "task_id": str(task_id),
                "location_name": location.name,
                "template_task_title": template_task.title,
                "operator_name": actor.full_name,
                "reason": reason,
            },
        )

        WAIVER_REQUESTS_TOTAL.labels(status=WAIVER_STATUS_OPEN).inc()
    finally:
        await session.close()


async def dispatch_waiver_decision(
    *,
    task_id: uuid.UUID,
    decision: str,
    decided_by: uuid.UUID,
) -> None:
    session = _open_session()
    try:
        row = (
            await session.execute(
                select(TaskInstance, Shift, TemplateTask, User)
                .join(Shift, Shift.id == TaskInstance.shift_id)
                .join(TemplateTask, TemplateTask.id == TaskInstance.template_task_id)
                .join(User, User.id == Shift.operator_user_id)
                .where(TaskInstance.id == task_id)
            )
        ).first()
        if row is None:
            return
        _task, shift, template_task, operator = row
        operator_chat = await _resolve_operator_dm_id(session, operator.id)
        if not operator_chat:
            return
        if decision == "approve":
            text = f"✅ Ваш waiver на задачу «{template_task.title}» одобрен."
        else:
            text = (
                f"❌ Waiver на «{template_task.title}» отклонён. "
                "Задача снова в pending — пожалуйста, выполните."
            )
        await send_telegram_message.kiq(operator_chat, text)

        await publish_event(
            organization_id=shift.organization_id,
            event_type="waiver.decided",
            data={
                "shift_id": str(shift.id),
                "task_id": str(task_id),
                "template_task_title": template_task.title,
                "decision": decision,
            },
        )

        WAIVER_DECISIONS_TOTAL.labels(decision=decision).inc()
        # Mirror the decision into the lifecycle counter so the funnel
        # `requests_total{status="open"}` → `{status="approved"|"rejected"}`
        # is computable from a single metric in dashboards.
        request_status = (
            WAIVER_STATUS_APPROVED if decision == "approve" else WAIVER_STATUS_REJECTED
        )
        WAIVER_REQUESTS_TOTAL.labels(status=request_status).inc()
        _ = decided_by
    finally:
        await session.close()


async def dispatch_shift_closed(*, shift_id: uuid.UUID, final_status: str) -> None:
    session = _open_session()
    try:
        row = (
            await session.execute(
                select(Shift, Location, Template, User)
                .join(Location, Location.id == Shift.location_id)
                .join(Template, Template.id == Shift.template_id)
                .join(User, User.id == Shift.operator_user_id)
                .where(Shift.id == shift_id)
            )
        ).first()
        if row is None:
            return
        shift, location, template, operator = row

        score_text = f"score {shift.score}%" if shift.score is not None else "score n/a"
        if final_status == "closed_clean":
            head = f"✅ [{location.name}] {operator.full_name} закрыл «{template.name}» — {score_text}, без нарушений"
        else:
            head = f"🟠 [{location.name}] {operator.full_name} закрыл «{template.name}» с нарушениями — {score_text}"

        admin_chat_id = location.tg_admin_chat_id
        owner_chats = await _resolve_owner_dm_ids(session, shift.organization_id)

        # Collect all photos for the shift and batch into media groups (max 10).
        attachments_stmt = (
            select(Attachment)
            .join(TaskInstance, TaskInstance.id == Attachment.task_instance_id)
            .where(TaskInstance.shift_id == shift_id)
            .order_by(Attachment.captured_at_server.asc())
        )
        attachments = (await session.execute(attachments_stmt)).scalars().all()

        if admin_chat_id:
            await send_telegram_message.kiq(admin_chat_id, head)
        for owner_chat in owner_chats:
            await send_telegram_message.kiq(owner_chat, head)

        await publish_event(
            organization_id=shift.organization_id,
            event_type="shift.closed",
            data={
                "shift_id": str(shift.id),
                "location_id": str(location.id),
                "location_name": location.name,
                "template_name": template.name,
                "operator_id": str(operator.id),
                "operator_name": operator.full_name,
                "final_status": final_status,
                "score": str(shift.score) if shift.score is not None else None,
                "actual_end": shift.actual_end.isoformat() if shift.actual_end else None,
            },
        )

        SHIFTS_CLOSED_TOTAL.labels(
            location_id=str(location.id), status=final_status
        ).inc()

        # Per-violation breakdown. The CloseShiftUseCase has already
        # marked missed required tasks as `skipped` and persisted
        # `actual_end`, so we can read the final state authoritatively
        # off the same row.
        await _emit_violation_metrics(
            session=session, shift=shift, location_id=str(location.id)
        )

        for batch_start in range(0, len(attachments), 10):
            chunk = attachments[batch_start : batch_start + 10]
            media = [
                {
                    "type": "photo",
                    "media": a.tg_file_id,
                    "caption": "⚠️ suspicious" if a.suspicious else "",
                }
                for a in chunk
                if a.tg_file_id  # R2 attachments need a different path (V2)
            ]
            if not media:
                continue
            if admin_chat_id:
                await send_telegram_media_group.kiq(admin_chat_id, media)
            for owner_chat in owner_chats:
                await send_telegram_media_group.kiq(owner_chat, media)
    finally:
        await session.close()
