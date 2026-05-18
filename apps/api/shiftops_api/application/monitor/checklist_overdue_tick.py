"""Periodic sweep: active shifts with incomplete checklist past the alert threshold.

Anti-overlap guarantee
----------------------
Each alert window is uniquely identified by ``(shift_id, window_index)`` where::

    window_index = (elapsed_min - delay_min) // repeat_min

The Redis key ``shiftops:checklist_overdue:{shift_id}:{window_index}`` is written
via SET NX with TTL ``repeat_min * 60 + 60``.  Two concurrent ticks in the same
minute race to SET NX on the same key — only the first succeeds; the second is a
no-op.  When the TTL expires the next window index is already different, so the
previous key never blocks a later alert.

Example (delay=60, repeat=5, max_alerts=12):
  elapsed 62 min → window 0 → key ``..:{shift_id}:0`` TTL=360 s
  elapsed 67 min → window 1 → key ``..:{shift_id}:1`` TTL=360 s
  ...
  elapsed 115 min → window 11 → last alert (11 < 12)
  elapsed 120 min → window 12 → 12 >= max_alerts → stop
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import redis.asyncio as redis_async
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.organizations.notification_prefs_config import (
    NotificationPrefsConfig,
)
from shiftops_api.domain.enums import ShiftStatus, TaskStatus
from shiftops_api.infra.db.models import Location, Organization, Shift, TaskInstance, Template, User
from shiftops_api.infra.db.rls import enter_privileged_rls_mode

_log = logging.getLogger(__name__)

# Global minimum look-back to bound the query (the shortest possible delay_min).
_MIN_DELAY_MIN = 10


@dataclass(frozen=True, slots=True)
class ChecklistOverdueReport:
    candidates: int
    sent: int
    skipped_disabled: int
    skipped_no_pending: int
    skipped_dedup: int


class ChecklistOverdueTickUseCase:
    def __init__(
        self,
        *,
        session: AsyncSession,
        redis: redis_async.Redis,
        now: datetime | None = None,
    ) -> None:
        self._session = session
        self._redis = redis
        self._now = (now or datetime.now(tz=UTC)).astimezone(UTC)

    async def execute(self) -> ChecklistOverdueReport:
        await enter_privileged_rls_mode(self._session, reason="checklist_overdue_tick")

        now = self._now
        cutoff = now - timedelta(minutes=_MIN_DELAY_MIN)

        # One query: active shifts that started long enough ago, joined with
        # org notification_prefs and location for the admin chat.
        rows = (
            await self._session.execute(
                select(Shift, Organization.notification_prefs, Location, Template, User)
                .join(Organization, Organization.id == Shift.organization_id)
                .join(Location, Location.id == Shift.location_id)
                .join(Template, Template.id == Shift.template_id)
                .join(User, User.id == Shift.operator_user_id)
                .where(Shift.status == ShiftStatus.ACTIVE.value)
                .where(Shift.actual_start.is_not(None))
                .where(Shift.actual_start <= cutoff)
            )
        ).all()

        if not rows:
            return ChecklistOverdueReport(
                candidates=0, sent=0,
                skipped_disabled=0, skipped_no_pending=0, skipped_dedup=0,
            )

        # Batch-load pending task counts for all candidate shifts at once.
        shift_ids = [row[0].id for row in rows]
        pending_counts: dict[Any, int] = {
            r.shift_id: int(r.cnt)
            for r in (
                await self._session.execute(
                    select(TaskInstance.shift_id, func.count(TaskInstance.id).label("cnt"))
                    .where(TaskInstance.shift_id.in_(shift_ids))
                    .where(
                        TaskInstance.status.in_([
                            TaskStatus.PENDING.value,
                            TaskStatus.WAIVER_PENDING.value,
                            TaskStatus.WAIVER_REJECTED.value,
                        ])
                    )
                    .group_by(TaskInstance.shift_id)
                )
            ).all()
        }

        sent = skipped_disabled = skipped_no_pending = skipped_dedup = 0

        for shift, raw_prefs, location, template, operator in rows:
            prefs = NotificationPrefsConfig.parse_storage(
                raw_prefs if isinstance(raw_prefs, dict) else {}
            ).checklist_overdue

            if not prefs.enabled:
                skipped_disabled += 1
                continue

            elapsed_min = int((now - shift.actual_start).total_seconds() // 60)
            if elapsed_min < prefs.delay_min:
                skipped_disabled += 1
                continue

            window_index = (elapsed_min - prefs.delay_min) // prefs.repeat_min
            if window_index >= prefs.max_alerts:
                skipped_disabled += 1
                continue

            pending = pending_counts.get(shift.id, 0)
            if pending == 0:
                skipped_no_pending += 1
                continue

            key = f"shiftops:checklist_overdue:{shift.id}:{window_index}"
            ttl = prefs.repeat_min * 60 + 60
            try:
                acquired = await self._redis.set(key, "1", nx=True, ex=ttl)
            except Exception:
                _log.warning("checklist_overdue.redis_failed", extra={"shift_id": str(shift.id)})
                continue

            if not acquired:
                skipped_dedup += 1
                continue

            # Lazy import to avoid circular dependency.
            from shiftops_api.infra.notifications.dispatcher import dispatch_checklist_overdue  # noqa: PLC0415

            await dispatch_checklist_overdue(
                shift_id=shift.id,
                elapsed_min=elapsed_min,
                pending_count=pending,
            )
            sent += 1
            _log.info(
                "checklist_overdue.sent",
                extra={
                    "shift_id": str(shift.id),
                    "elapsed_min": elapsed_min,
                    "window": window_index,
                    "pending": pending,
                },
            )

        return ChecklistOverdueReport(
            candidates=len(rows),
            sent=sent,
            skipped_disabled=skipped_disabled,
            skipped_no_pending=skipped_no_pending,
            skipped_dedup=skipped_dedup,
        )


__all__ = ["ChecklistOverdueReport", "ChecklistOverdueTickUseCase"]
