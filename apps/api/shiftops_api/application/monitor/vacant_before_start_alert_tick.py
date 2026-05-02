"""Periodic sweep: vacant scheduled shifts starting soon — alert admin chat once.

Runs in the TaskIQ worker with privileged RLS. Dedup per shift via Redis SET NX
so we do not spam the admin group on every minute tick.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import redis.asyncio as redis_async
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.config import get_settings
from shiftops_api.domain.enums import ShiftStatus
from shiftops_api.infra.db.models import Location, Shift
from shiftops_api.infra.db.rls import enter_privileged_rls_mode
from shiftops_api.infra.notifications.dispatcher import dispatch_vacant_before_start_alert

_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class VacantBeforeStartAlertReport:
    candidates: int
    sent: int
    skipped_no_admin_chat: int


class VacantBeforeStartAlertTickUseCase:
    """Find pool slots (no operator) whose scheduled start is within the
    configured window; enqueue at most one Telegram alert per shift (Redis)."""

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

    async def execute(self) -> VacantBeforeStartAlertReport:
        settings = get_settings()
        window = timedelta(minutes=settings.vacant_before_start_alert_min)
        now = self._now

        await enter_privileged_rls_mode(self._session, reason="vacant_before_start_alert_tick")

        stmt = (
            select(Shift, Location)
            .join(Location, Location.id == Shift.location_id)
            .where(Shift.status == ShiftStatus.SCHEDULED.value)
            .where(Shift.operator_user_id.is_(None))
            .where(Shift.scheduled_start > now)
            .where(Shift.scheduled_start <= now + window)
        )
        rows = (await self._session.execute(stmt)).all()

        sent = 0
        skipped_chat = 0
        for shift, loc in rows:
            if loc.tg_admin_chat_id is None:
                skipped_chat += 1
                continue
            key = f"shiftops:vacant_before_start:{shift.id}"
            ttl_sec = int((shift.scheduled_start - now).total_seconds()) + 300
            ttl_sec = max(60, min(ttl_sec, 86_400))
            try:
                ok = await self._redis.set(key, "1", nx=True, ex=ttl_sec)
            except Exception:
                _log.warning("vacant_before_start.redis_failed", extra={"shift_id": str(shift.id)})
                continue
            if ok:
                await dispatch_vacant_before_start_alert(shift_id=shift.id)
                sent += 1

        await self._session.commit()
        return VacantBeforeStartAlertReport(
            candidates=len(rows),
            sent=sent,
            skipped_no_admin_chat=skipped_chat,
        )


__all__ = ["VacantBeforeStartAlertTickUseCase", "VacantBeforeStartAlertReport"]
