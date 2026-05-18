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
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.domain.enums import ShiftStatus, UserRole
from shiftops_api.infra.db.engine import get_sessionmaker
from shiftops_api.infra.db.models import (
    Attachment,
    Location,
    Shift,
    ShiftSwapRequest,
    TaskInstance,
    TelegramAccount,
    Template,
    TemplateTask,
    User,
)
from shiftops_api.infra.db.rls import enter_privileged_rls_mode
from shiftops_api.infra.metrics import (
    ATTACHMENT_LOW_LUMINANCE_TOTAL,
    ATTACHMENT_PHASH_COLLISIONS_TOTAL,
    SHIFTS_CLOSED_TOTAL,
    SHIFTS_STARTED_TOTAL,
    TASKS_COMPLETED_TOTAL,
    VIOLATION_TYPE_INCOMPLETE_REQUIRED,
    VIOLATION_TYPE_LATE_CLOSE,
    VIOLATION_TYPE_LOW_LUMINANCE,
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

_ROLE_RU: dict[str, str] = {
    "owner": "владелец",
    "admin": "администратор",
    "operator": "оператор",
    "bartender": "бармен",
}


def _op_label(operator: User) -> str:
    """'Иван Петров (оператор)'"""
    role_ru = _ROLE_RU.get(str(operator.role), str(operator.role))
    return f"{operator.full_name} ({role_ru})"


def _fmt_local_hhmm(dt: datetime | None, tz_name: str | None) -> str:
    """Format UTC timestamp in a location timezone for Telegram copy."""
    if dt is None:
        return "?"
    try:
        tz = ZoneInfo(tz_name or "UTC")
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    return dt.astimezone(tz).strftime("%H:%M")


def _open_session() -> AsyncSession:
    """Open an unmanaged session — caller is responsible for `await session.close()`."""
    factory = get_sessionmaker()
    return factory()


@asynccontextmanager
async def _privileged_session() -> AsyncIterator[AsyncSession]:
    """Open a session with RLS bypass for cross-tenant notification dispatchers.

    Notifications run outside a per-request tenant transaction. Without the
    bypass role, FORCE RLS silently returns 0 rows (no org GUC set), causing
    all dispatcher lookups to fail quietly.
    """
    session = _open_session()
    try:
        await enter_privileged_rls_mode(session, reason="notification_dispatch")
        yield session
    finally:
        await session.close()


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
        .where(User.role == UserRole.OWNER)
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


async def dispatch_shift_assigned(*, shift_id: uuid.UUID) -> None:
    """DM to operator when the recurring tick creates a scheduled shift for them."""
    async with _privileged_session() as session:
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
        operator_chat = await _resolve_operator_dm_id(session, operator.id)
        if not operator_chat:
            return
        start_time = _fmt_local_hhmm(shift.scheduled_start, location.timezone)
        end_time = _fmt_local_hhmm(shift.scheduled_end, location.timezone)
        msg = (
            f"📋 [{location.name}] Ваша смена «{template.name}» сегодня с {start_time} до {end_time}.\n"
            f"Откройте приложение ShiftOps и начните выполнять задачи вовремя."
        )
        await send_telegram_message.kiq(operator_chat, msg)


async def dispatch_shift_opened(*, shift_id: uuid.UUID) -> None:
    async with _privileged_session() as session:
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
            f"🟢 [{location.name}] {_op_label(operator)} начал «{template.name}» в "
            f"{_fmt_local_hhmm(shift.actual_start, location.timezone)}"
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
                "actual_start": (shift.actual_start.isoformat() if shift.actual_start else None),
            },
        )

        SHIFTS_STARTED_TOTAL.labels(
            location_id=str(location.id),
            template_id=str(template.id),
        ).inc()


async def dispatch_vacant_before_start_alert(*, shift_id: uuid.UUID) -> None:
    """Proactive ping: scheduled pool slot still has no operator shortly before open."""
    async with _privileged_session() as session:
        row = (
            await session.execute(
                select(Shift, Location, Template)
                .join(Location, Location.id == Shift.location_id)
                .join(Template, Template.id == Shift.template_id)
                .where(Shift.id == shift_id)
            )
        ).first()
        if row is None:
            return
        shift, location, template = row
        if shift.operator_user_id is not None:
            return
        if shift.status != ShiftStatus.SCHEDULED.value:
            return
        now = datetime.now(tz=UTC)
        if shift.scheduled_start <= now:
            return
        minutes_left = max(1, int((shift.scheduled_start - now).total_seconds() // 60))
        post_label = (shift.station_label and shift.station_label.strip()) or f"слот {shift.slot_index}"
        text = (
            f"⚠️ Внимание! Пост [{post_label}] всё ещё свободен! Старт через {minutes_left} мин\n"
            f"«{template.name}» · {location.name}"
        )
        admin_chat_id = location.tg_admin_chat_id
        if admin_chat_id:
            await send_telegram_message.kiq(admin_chat_id, text)
        owner_chats = await _resolve_owner_dm_ids(session, shift.organization_id)
        for owner_chat in owner_chats:
            await send_telegram_message.kiq(owner_chat, text)


async def dispatch_task_progress(
    *,
    shift_id: uuid.UUID,
    task_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    new_status: str,
    phash_collision: bool = False,
    low_luminance: bool = False,
) -> None:
    """Publish a real-time progress event for the admin live monitor."""
    async with _privileged_session() as session:
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
        shift, location, template_task, _ = row

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

        suspicious = phash_collision or low_luminance
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
                "phash_collision": phash_collision,
                "low_luminance": low_luminance,
                "progress_total": int(progress_row.total or 0),
                "progress_done": int(progress_row.done or 0),
            },
        )

        if new_status == "done":
            TASKS_COMPLETED_TOTAL.labels(criticality=str(template_task.criticality)).inc()
            if phash_collision:
                ATTACHMENT_PHASH_COLLISIONS_TOTAL.inc()
                VIOLATIONS_TOTAL.labels(
                    type=VIOLATION_TYPE_PHASH_COLLISION,
                    location_id=str(location.id),
                ).inc()
            if low_luminance:
                ATTACHMENT_LOW_LUMINANCE_TOTAL.inc()
                VIOLATIONS_TOTAL.labels(
                    type=VIOLATION_TYPE_LOW_LUMINANCE,
                    location_id=str(location.id),
                ).inc()


async def dispatch_suspicious_photo_alert(
    *,
    shift_id: uuid.UUID,
    task_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> None:
    async with _privileged_session() as session:
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


async def dispatch_waiver_request(
    *,
    task_id: uuid.UUID,
    shift_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    reason: str,
) -> None:
    async with _privileged_session() as session:
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


async def dispatch_waiver_decision(
    *,
    task_id: uuid.UUID,
    decision: str,
    decided_by: uuid.UUID,
) -> None:
    async with _privileged_session() as session:
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
                "decided_by": str(decided_by),
            },
        )

        WAIVER_DECISIONS_TOTAL.labels(decision=decision).inc()
        request_status = WAIVER_STATUS_APPROVED if decision == "approve" else WAIVER_STATUS_REJECTED
        WAIVER_REQUESTS_TOTAL.labels(status=request_status).inc()


async def dispatch_shift_closed(*, shift_id: uuid.UUID, final_status: str) -> None:
    async with _privileged_session() as session:
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
            head = (
                f"✅ [{location.name}] {_op_label(operator)} закрыл «{template.name}»"
                f" — {score_text}, без нарушений"
            )
        else:
            head = (
                f"🟠 [{location.name}] {_op_label(operator)} закрыл «{template.name}»"
                f" с нарушениями — {score_text}"
            )
        if shift.violation_reason:
            head += f"\nПричина: {shift.violation_reason}"

        admin_chat_id = location.tg_admin_chat_id
        owner_chats = await _resolve_owner_dm_ids(session, shift.organization_id)

        # Collect all photos with their task titles for captioned media groups.
        attachments_stmt = (
            select(Attachment, TemplateTask.title)
            .join(TaskInstance, TaskInstance.id == Attachment.task_instance_id)
            .join(TemplateTask, TemplateTask.id == TaskInstance.template_task_id)
            .where(TaskInstance.shift_id == shift_id)
            .order_by(Attachment.captured_at_server.asc())
        )
        attachment_rows = (await session.execute(attachments_stmt)).all()

        if admin_chat_id:
            await send_telegram_message.kiq(admin_chat_id, head)
        for owner_chat in owner_chats:
            await send_telegram_message.kiq(owner_chat, head)

        # ── Operator personal summary DM ──────────────────────────────────────
        operator_chat = await _resolve_operator_dm_id(session, operator.id)
        if operator_chat:
            task_rows = (
                await session.execute(
                    select(TaskInstance.status, TemplateTask.title, TemplateTask.criticality)
                    .join(TemplateTask, TemplateTask.id == TaskInstance.template_task_id)
                    .where(TaskInstance.shift_id == shift_id)
                    .order_by(TaskInstance.status)
                )
            ).all()
            total_tasks = len(task_rows)
            done_tasks = sum(1 for r in task_rows if r.status in ("done", "waived"))
            skipped = [r.title for r in task_rows if r.status == "skipped"]

            score_text = f"{shift.score}%" if shift.score is not None else "—"
            start_str = _fmt_local_hhmm(shift.actual_start, location.timezone)
            end_str = _fmt_local_hhmm(shift.actual_end, location.timezone)

            op_lines = [
                f"📋 Смена закрыта — {template.name}",
                f"🏠 {location.name}  {start_str} → {end_str}",
                f"⭐ Ваш балл: {score_text}",
                f"✅ Выполнено: {done_tasks}/{total_tasks}",
            ]
            if skipped:
                op_lines.append("❌ Пропущено: " + ", ".join(f"«{t}»" for t in skipped))
            await send_telegram_message.kiq(operator_chat, "\n".join(op_lines))

        # Handover summary: persisted at close time for audit stability.
        if shift.handover_summary:
            if admin_chat_id:
                await send_telegram_message.kiq(admin_chat_id, shift.handover_summary)
            for owner_chat in owner_chats:
                await send_telegram_message.kiq(owner_chat, shift.handover_summary)

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

        SHIFTS_CLOSED_TOTAL.labels(location_id=str(location.id), status=final_status).inc()

        await _emit_violation_metrics(session=session, shift=shift, location_id=str(location.id))

        for batch_start in range(0, len(attachment_rows), 10):
            chunk = attachment_rows[batch_start : batch_start + 10]
            media = []
            for attachment, task_title in chunk:
                if not attachment.tg_file_id:  # R2 attachments need a different path (V2)
                    continue
                caption_parts = [f"📋 {task_title}"]
                if attachment.suspicious:
                    caption_parts.append("⚠️ подозрительное")
                media.append(
                    {
                        "type": "photo",
                        "media": attachment.tg_file_id,
                        "caption": " · ".join(caption_parts),
                    }
                )
            if not media:
                continue
            if admin_chat_id:
                await send_telegram_media_group.kiq(admin_chat_id, media)
            for owner_chat in owner_chats:
                await send_telegram_media_group.kiq(owner_chat, media)


async def dispatch_swap_request_created(*, request_id: uuid.UUID) -> None:
    async with _privileged_session() as session:
        req = await session.get(ShiftSwapRequest, request_id)
        if req is None:
            return
        proposer = await session.get(User, req.proposer_user_id)
        if proposer is None:
            return
        text = (
            f"🔀 {proposer.full_name} предлагает обмен запланированными сменами. "
            "Откройте ShiftOps (TWA) → «Запросы на обмен», чтобы принять или отклонить."
        )
        dm = await _resolve_operator_dm_id(session, req.counterparty_user_id)
        if dm:
            await send_telegram_message.kiq(dm, text)


async def dispatch_swap_request_resolved(*, request_id: uuid.UUID, accepted: bool) -> None:
    async with _privileged_session() as session:
        req = await session.get(ShiftSwapRequest, request_id)
        if req is None:
            return
        proposer = await session.get(User, req.proposer_user_id)
        counterparty = await session.get(User, req.counterparty_user_id)
        if proposer is None or counterparty is None:
            return
        if accepted:
            body = f"✅ {counterparty.full_name} принял(а) обмен сменами с {proposer.full_name}."
        else:
            body = f"❌ {counterparty.full_name} отклонил(а) обмен сменами."
        for uid in (req.proposer_user_id, req.counterparty_user_id):
            dm = await _resolve_operator_dm_id(session, uid)
            if dm:
                await send_telegram_message.kiq(dm, body)
