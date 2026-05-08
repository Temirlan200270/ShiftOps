"""TaskIQ periodic tasks for shift recurrence.

The ``recurring_shifts_tick`` task fires every minute. Each invocation
opens its own DB session (we cannot share a request session here, this
runs in the worker process), constructs the use case, and commits.

We deliberately avoid TaskIQ result tracking (``Depends`` + result
backend) — the tick is a sweep; if it crashes we'd rather see a
Sentry breadcrumb and let the next minute's tick recover than block
the broker on a stuck retry chain.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import redis.asyncio as redis_async
from sqlalchemy import delete, select
from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource

from shiftops_api.application.monitor.vacant_before_start_alert_tick import (
    VacantBeforeStartAlertTickUseCase,
)
from shiftops_api.application.templates.recurring_shifts_tick import (
    CreateRecurringShiftsTickUseCase,
)
from shiftops_api.config import get_settings
from shiftops_api.domain.enums import ShiftStatus
from shiftops_api.infra.db.engine import get_sessionmaker
from shiftops_api.infra.db.models import Location, Organization, Shift, TelegramAccount, User
from shiftops_api.infra.db.rls import enter_privileged_rls_mode
from shiftops_api.infra.metrics import (
    RECURRING_SHIFTS_CREATED_TOTAL,
    RECURRING_TICK_CREATED_LAST,
    RECURRING_TICK_TEMPLATES_VISIBLE,
    SHIFT_REMINDERS_SENT_TOTAL,
    SHIFT_REMINDERS_SKIPPED_TOTAL,
)
from shiftops_api.infra.notifications.tasks import send_telegram_message
from shiftops_api.infra.queue import broker

_REMINDER_TTL_SECONDS = 48 * 3600  # deduplicate for 48 h

_log = logging.getLogger(__name__)


@broker.task(
    task_name="shiftops.recurring_shifts_tick",
    schedule=[{"cron": "* * * * *"}],
)
async def recurring_shifts_tick() -> dict[str, int]:
    """Cron: every minute. Materialises shifts whose recurrence window
    is open right now. Returns a tiny report for logs / dashboards.
    """

    factory = get_sessionmaker()
    async with factory() as session:
        use_case = CreateRecurringShiftsTickUseCase(session=session)
        report = await use_case.execute()

    # Canary metrics: if FORCE RLS blocks the worker, inspected will drop to 0.
    RECURRING_TICK_TEMPLATES_VISIBLE.set(report.inspected)
    RECURRING_TICK_CREATED_LAST.set(report.created)
    if report.created:
        RECURRING_SHIFTS_CREATED_TOTAL.inc(report.created)

    _log.info(
        "recurring.tick.summary",
        extra={
            "inspected": report.inspected,
            "created": report.created,
            "skipped": report.skipped,
            "aborted_expired_vacant": report.aborted_expired_vacant,
        },
    )
    return {
        "inspected": report.inspected,
        "created": report.created,
        "skipped": report.skipped,
        "aborted_expired_vacant": report.aborted_expired_vacant,
    }


@broker.task(
    task_name="shiftops.vacant_before_start_alert_tick",
    schedule=[{"cron": "* * * * *"}],
)
async def vacant_before_start_alert_tick() -> dict[str, int]:
    """Cron: every minute. Ping admin chat if a vacant pool slot opens within the window."""

    settings = get_settings()
    redis = redis_async.from_url(settings.redis_url)
    factory = get_sessionmaker()
    try:
        async with factory() as session:
            use_case = VacantBeforeStartAlertTickUseCase(session=session, redis=redis)
            report = await use_case.execute()
    finally:
        await redis.aclose()

    _log.info(
        "vacant_before_start_alert.summary",
        extra={
            "candidates": report.candidates,
            "sent": report.sent,
            "skipped_no_admin_chat": report.skipped_no_admin_chat,
        },
    )
    return {
        "candidates": report.candidates,
        "sent": report.sent,
        "skipped_no_admin_chat": report.skipped_no_admin_chat,
    }


async def _send_reminder_once(
    redis: redis_async.Redis,
    key: str,
    chat_id: int,
    text: str,
    *,
    ttl: int = _REMINDER_TTL_SECONDS,
) -> bool:
    """SET key NX EX ttl → returns True if message was sent (key was new)."""
    acquired = await redis.set(key, "1", ex=ttl, nx=True)
    if not acquired:
        return False
    await send_telegram_message.kiq(chat_id, text)
    return True


@broker.task(
    task_name="shiftops.shift_reminders_tick",
    schedule=[{"cron": "* * * * *"}],
)
async def shift_reminders_tick() -> dict[str, int]:
    """Cron: every minute. Reminder DMs for upcoming/overdue *scheduled* shifts and
    for *active* shifts not closed within 1 hour.

    Scheduled-shift matrix (m = minutes until scheduled_start):
      T-30 :  0 < m <= 30   → "starts in 30 min"
      T+0  : -15 < m <= 0   → "should have started"
      T+15 : -30 < m <= -15 → "15+ min overdue"
      T+30 :  m <= -30       → "30+ min overdue, manager notified"

    Active-shift check:
      If a shift has been active (open checklist) for more than 60 min without closing →
      notify operator + owner once.
    """
    settings = get_settings()
    redis = redis_async.from_url(settings.redis_url)
    factory = get_sessionmaker()
    sent = 0
    skipped = 0

    try:
        now = datetime.now(tz=UTC)

        # ── Scheduled-shift reminders ─────────────────────────────────────────
        sched_window_start = now - timedelta(minutes=45)
        sched_window_end = now + timedelta(minutes=35)

        async with factory() as session:
            await enter_privileged_rls_mode(session, reason="shift_reminders_tick")
            sched_rows = (
                await session.execute(
                    select(Shift, Location, User, TelegramAccount)
                    .join(Location, Location.id == Shift.location_id)
                    .join(User, User.id == Shift.operator_user_id)
                    .join(TelegramAccount, TelegramAccount.user_id == User.id)
                    .where(Shift.status == ShiftStatus.SCHEDULED.value)
                    .where(Shift.operator_user_id.is_not(None))
                    .where(Shift.scheduled_start >= sched_window_start)
                    .where(Shift.scheduled_start <= sched_window_end)
                )
            ).all()

            # ── Active-shift 1-hour reminder ─────────────────────────────────
            # Shifts opened more than 60 min ago that are still active.
            active_cutoff = now - timedelta(minutes=60)
            active_rows = (
                await session.execute(
                    select(Shift, Location, User, TelegramAccount)
                    .join(Location, Location.id == Shift.location_id)
                    .join(User, User.id == Shift.operator_user_id)
                    .join(TelegramAccount, TelegramAccount.user_id == User.id)
                    .where(Shift.status == ShiftStatus.ACTIVE.value)
                    .where(Shift.operator_user_id.is_not(None))
                    .where(Shift.actual_start.is_not(None))
                    .where(Shift.actual_start <= active_cutoff)
                )
            ).all()

        for shift, location, operator, tg_account in sched_rows:
            if not tg_account.tg_user_id:
                continue
            m = (shift.scheduled_start - now).total_seconds() / 60
            post = f" «{shift.station_label}»" if shift.station_label else ""

            candidates: list[tuple[str, str]] = []
            if 0 < m <= 30:
                candidates.append(("t30", f"⏰ [{location.name}] {operator.full_name}, через 30 минут начинается ваша смена{post}. Не забудьте открыть приложение ShiftOps и приступить к заданиям."))
            elif -15 < m <= 0:
                candidates.append(("t0", f"🔴 [{location.name}] {operator.full_name}, ваша смена{post} уже должна была начаться! Откройте ShiftOps и начните выполнять задания."))
            elif -30 < m <= -15:
                candidates.append(("t15", f"🚨 [{location.name}] {operator.full_name}, вы опаздываете на смену{post} уже более 15 минут. Немедленно откройте ShiftOps!"))
            elif m <= -30:
                candidates.append(("t30_late", f"🚨🚨 [{location.name}] {operator.full_name}, смена{post} не начата уже 30+ минут. Руководитель получил уведомление."))

            for key_suffix, text in candidates:
                rkey = f"shiftops:reminder:{shift.id}:{key_suffix}"
                ok = await _send_reminder_once(redis, rkey, tg_account.tg_user_id, text)
                if ok:
                    sent += 1
                    SHIFT_REMINDERS_SENT_TOTAL.labels(milestone=key_suffix).inc()
                else:
                    skipped += 1
                    SHIFT_REMINDERS_SKIPPED_TOTAL.labels(milestone=key_suffix).inc()

        # ── Active-shift 1-hour unclosed notification ─────────────────────────
        for shift, location, operator, tg_account in active_rows:
            if not tg_account.tg_user_id:
                continue
            post = f" «{shift.station_label}»" if shift.station_label else ""
            elapsed_min = int((now - shift.actual_start).total_seconds() // 60)

            op_key = f"shiftops:reminder:{shift.id}:active_1h_op"
            op_text = (
                f"⏰ [{location.name}] {operator.full_name}, ваша смена{post} открыта уже "
                f"{elapsed_min} мин, но ещё не закрыта. Пожалуйста, завершите чек-лист и закройте смену."
            )
            ok = await _send_reminder_once(redis, op_key, tg_account.tg_user_id, op_text)
            if ok:
                sent += 1
                SHIFT_REMINDERS_SENT_TOTAL.labels(milestone="active_1h_op").inc()
            else:
                skipped += 1
                SHIFT_REMINDERS_SKIPPED_TOTAL.labels(milestone="active_1h_op").inc()

        # Notify owner about unclosed active shifts via dispatcher (uses its own session + RLS).
        for shift, location, operator, _tg_account in active_rows:
            owner_key = f"shiftops:reminder:{shift.id}:active_1h_owner"
            # Atomic SET NX — only one worker wins even under concurrent ticks.
            acquired = await redis.set(owner_key, "1", ex=_REMINDER_TTL_SECONDS, nx=True)
            if not acquired:
                skipped += 1
                SHIFT_REMINDERS_SKIPPED_TOTAL.labels(milestone="active_1h_owner").inc()
                continue
            # Lazy import to avoid circular: tasks → dispatcher → notifications/tasks → queue → tasks
            from shiftops_api.infra.notifications.dispatcher import _privileged_session, _resolve_owner_dm_ids  # noqa: PLC0415, I001
            async with _privileged_session() as session:
                owner_chats = await _resolve_owner_dm_ids(session, shift.organization_id)
            if owner_chats:
                post = f" «{shift.station_label}»" if shift.station_label else ""
                elapsed_min = int((now - shift.actual_start).total_seconds() // 60)
                owner_text = (
                    f"⚠️ [{location.name}] Смена{post} сотрудника {operator.full_name} "
                    f"открыта уже {elapsed_min} мин и не закрыта. Проверьте статус."
                )
                for oc in owner_chats:
                    await send_telegram_message.kiq(oc, owner_text)
                sent += len(owner_chats)
                SHIFT_REMINDERS_SENT_TOTAL.labels(milestone="active_1h_owner").inc(len(owner_chats))

    finally:
        await redis.aclose()

    _log.info("shift_reminders_tick.summary", extra={"sent": sent, "skipped": skipped})
    return {"sent": sent, "skipped": skipped}


@broker.task(
    task_name="shiftops.purge_deleted_orgs_tick",
    schedule=[{"cron": "27 4 * * *"}],
)
async def purge_deleted_orgs_tick() -> dict[str, int]:
    """Daily: hard-delete organizations past the soft-delete retention window."""

    settings = get_settings()
    cutoff = datetime.now(tz=UTC) - timedelta(days=settings.org_deletion_retention_days)
    factory = get_sessionmaker()
    async with factory() as session:
        await enter_privileged_rls_mode(session, reason="purge_deleted_orgs_list")
        ids = list(
            (
                await session.execute(
                    select(Organization.id).where(
                        Organization.deleted_at.isnot(None),
                        Organization.deleted_at <= cutoff,
                    )
                )
            ).scalars().all()
        )
        await session.commit()

    purged = 0
    for oid in ids:
        async with factory() as s:
            await enter_privileged_rls_mode(s, reason="purge_deleted_org")
            try:
                await s.execute(delete(Organization).where(Organization.id == oid))
                await s.commit()
                purged += 1
            except Exception:
                await s.rollback()
                _log.warning("purge_org_failed", extra={"organization_id": str(oid)})

    _log.info(
        "purge_deleted_orgs.summary",
        extra={"candidates": len(ids), "purged": purged},
    )
    return {"candidates": len(ids), "purged": purged}


# Re-export `scheduler` from the broker module so the worker entrypoint
# (`taskiq scheduler ...`) can find the `LabelScheduleSource`.
__all__ = [
    "purge_deleted_orgs_tick",
    "recurring_shifts_tick",
    "shift_reminders_tick",
    "vacant_before_start_alert_tick",
]


# Defensive import: the worker might import only `infra.queue` (via the
# `import_tasks()` hook) — a side-effect import here registers the cron
# task on the same broker instance.
_ = TaskiqScheduler  # silence unused-import linters
_ = LabelScheduleSource
