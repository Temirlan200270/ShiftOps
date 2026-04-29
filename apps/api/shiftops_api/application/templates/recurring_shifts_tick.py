"""Materialise scheduled shifts from a template's recurrence config.

This is the engine behind "the checklist appears every day at 09:00 for
the admin and operator": the periodic tick reads each template's
``default_schedule``, decides whether *now* lands inside the day's
creation window, and inserts a ``Shift`` plus its ``TaskInstance`` rows
exactly once.

Why a tick (over a job per template)
------------------------------------
The pilot has tens of templates, not thousands. A single sweep every
minute is far simpler than per-template scheduling and survives missed
ticks (Fly machine restart, broker outage, deploy) — the next tick will
just notice "today's shift is missing" and create it.

Idempotency
-----------
The natural key is ``(template_id, location_id, scheduled_date_local)``.
Postgres has no unique partial index on that yet (it would require a
helper column), so the use case takes a row-level advisory lock per
``(template_id, location_id, day_local)`` to make a concurrent run a
no-op without two duplicate INSERTs slipping through.

Lead-window semantics
---------------------
Within the day the tick fires while ``time_of_day - lead_time_min ≤
now < time_of_day + 5 min``. Five minutes of trailing tolerance keeps
us robust to a transient DB outage; if we miss that window entirely
nobody gets a shift today, which is the right failure mode (a missed
checklist is better than a *late* one that the operator might not even
see).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.templates.recurrence import RecurrenceConfig, parse_storage
from shiftops_api.domain.enums import ShiftStatus, TaskStatus, UserRole
from shiftops_api.infra.db.models import (
    Location,
    Shift,
    TaskInstance,
    Template,
    TemplateTask,
    User,
)
from shiftops_api.infra.db.rls import enter_privileged_rls_mode

_log = logging.getLogger(__name__)
TRAILING_TOLERANCE_MIN = 5


def is_window_open(
    cfg: RecurrenceConfig,
    *,
    location_tz_name: str,
    now_utc: datetime,
) -> bool:
    """Pure decision: should *now* trigger a creation for this config?

    Splits the timezone math out of the use case so it can be unit-tested
    without a database session. Returns True when:

    - Today's local weekday is in ``cfg.weekdays``;
    - ``time_of_day - lead_time_min ≤ now_local ≤ time_of_day + 5 min``.
    """

    try:
        tz = ZoneInfo(cfg.timezone or location_tz_name or "UTC")
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")

    local_now = now_utc.astimezone(tz)
    if local_now.isoweekday() not in set(cfg.weekdays):
        return False
    scheduled_local = datetime.combine(local_now.date(), cfg.time_of_day, tzinfo=tz)
    window_open = scheduled_local - timedelta(minutes=cfg.lead_time_min)
    window_close = scheduled_local + timedelta(minutes=TRAILING_TOLERANCE_MIN)
    return window_open <= local_now <= window_close


@dataclass(frozen=True, slots=True)
class TickReport:
    """Summary returned to the periodic task / tests."""

    inspected: int
    created: int
    skipped: int


class CreateRecurringShiftsTickUseCase:
    """Sweep all templates with ``auto_create=true`` and ensure today's
    shift exists at the configured location.

    Caller responsibility: provide a session WITHOUT an ``app.org_id``
    GUC (the worker is not bound to a tenant). RLS still applies to
    queries — with ``FORCE ROW LEVEL SECURITY`` enabled, connecting as
    the DB owner is *not* enough. We explicitly bypass RLS via
    :func:`enter_privileged_rls_mode` for this sweep.
    """

    def __init__(self, *, session: AsyncSession, now: datetime | None = None) -> None:
        self._session = session
        self._now = (now or datetime.now(tz=UTC)).astimezone(UTC)

    async def execute(self) -> TickReport:
        # Worker is not bound to a tenant; it must see all orgs' templates.
        # With FORCE RLS enabled this requires an explicit bypass.
        await enter_privileged_rls_mode(self._session, reason="recurring_shifts_tick")

        # 1. Load all templates with a non-null default_schedule. We
        #    intentionally pull the full set (small, ~50 rows even at
        #    pilot scale) and filter in Python — the auto_create flag
        #    lives inside the JSONB blob and adding a generated column
        #    just for this filter is not worth the migration.
        rows = (
            (
                await self._session.execute(
                    select(Template).where(Template.default_schedule.is_not(None))
                )
            )
            .scalars()
            .all()
        )

        inspected = 0
        created = 0
        skipped = 0

        for template in rows:
            inspected += 1
            cfg = parse_storage(template.default_schedule)
            if cfg is None or not cfg.auto_create:
                skipped += 1
                continue

            try:
                made = await self._materialize_for(template, cfg)
            except Exception:  # noqa: BLE001 — must not crash the sweep
                _log.exception(
                    "recurring.tick.template_failed",
                    extra={
                        "template_id": str(template.id),
                    },
                )
                skipped += 1
                continue

            if made:
                created += 1
            else:
                skipped += 1

        await self._session.commit()
        return TickReport(inspected=inspected, created=created, skipped=skipped)

    async def _materialize_for(
        self,
        template: Template,
        cfg: RecurrenceConfig,
    ) -> bool:
        location = await self._session.get(Location, cfg.location_id)
        if location is None:
            _log.warning(
                "recurring.tick.location_missing",
                extra={
                    "template_id": str(template.id),
                    "location_id": str(cfg.location_id),
                },
            )
            return False

        if not is_window_open(
            cfg,
            location_tz_name=location.timezone or "UTC",
            now_utc=self._now,
        ):
            return False

        try:
            tz = ZoneInfo(cfg.timezone or location.timezone or "UTC")
        except ZoneInfoNotFoundError:
            tz = ZoneInfo("UTC")

        local_now = self._now.astimezone(tz)
        scheduled_local = datetime.combine(local_now.date(), cfg.time_of_day, tzinfo=tz)
        scheduled_start_utc = scheduled_local.astimezone(UTC)
        scheduled_end_utc = scheduled_start_utc + timedelta(minutes=cfg.duration_min)
        local_day: date = local_now.date()

        if await self._already_exists(template.id, location.id, local_day, tz):
            return False

        operator_id = await self._resolve_operator(template, cfg)
        if operator_id is None:
            _log.warning(
                "recurring.tick.no_operator",
                extra={
                    "template_id": str(template.id),
                    "organization_id": str(template.organization_id),
                },
            )
            return False

        # Advisory lock keyed by template + location + day so two ticks
        # racing on the same minute don't insert duplicates. The lock
        # is transaction-scoped (released on commit) and works on the
        # Supabase pooler.
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
            {"k": f"recurring:{template.id}:{location.id}:{local_day.isoformat()}"},
        )

        # Re-check after taking the lock — a concurrent winner may have
        # inserted between our existence check and the lock acquire.
        if await self._already_exists(template.id, location.id, local_day, tz):
            return False

        shift_id = uuid.uuid4()
        self._session.add(
            Shift(
                id=shift_id,
                organization_id=template.organization_id,
                location_id=location.id,
                template_id=template.id,
                operator_user_id=operator_id,
                scheduled_start=scheduled_start_utc,
                scheduled_end=scheduled_end_utc,
                status=ShiftStatus.SCHEDULED.value,
            )
        )

        tt_rows = (
            (
                await self._session.execute(
                    select(TemplateTask)
                    .where(TemplateTask.template_id == template.id)
                    .order_by(TemplateTask.order_index.asc())
                )
            )
            .scalars()
            .all()
        )
        for tt in tt_rows:
            self._session.add(
                TaskInstance(
                    shift_id=shift_id,
                    template_task_id=tt.id,
                    status=TaskStatus.PENDING.value,
                )
            )

        _log.info(
            "recurring.tick.created",
            extra={
                "template_id": str(template.id),
                "location_id": str(location.id),
                "shift_id": str(shift_id),
                "scheduled_start": scheduled_start_utc.isoformat(),
            },
        )
        return True

    async def _already_exists(
        self,
        template_id: uuid.UUID,
        location_id: uuid.UUID,
        local_day: date,
        tz: ZoneInfo,
    ) -> bool:
        # We don't have a pre-computed "scheduled_date_local" column, so we
        # bracket the search by [start_of_day_local, end_of_day_local]
        # converted to UTC. ZoneInfo handles DST transitions correctly.
        day_start_local = datetime.combine(local_day, datetime.min.time(), tzinfo=tz)
        day_end_local = day_start_local + timedelta(days=1)
        existing = (
            await self._session.execute(
                select(Shift.id)
                .where(Shift.template_id == template_id)
                .where(Shift.location_id == location_id)
                .where(Shift.scheduled_start >= day_start_local.astimezone(UTC))
                .where(Shift.scheduled_start < day_end_local.astimezone(UTC))
                .limit(1)
            )
        ).first()
        return existing is not None

    async def _resolve_operator(
        self,
        template: Template,
        cfg: RecurrenceConfig,
    ) -> uuid.UUID | None:
        if cfg.default_assignee_id is not None:
            user = await self._session.get(User, cfg.default_assignee_id)
            if user is not None and user.is_active:
                return user.id

        # Fallback: pick the first active user with the template's
        # role_target so the shift can be opened by *somebody*. Owners
        # are picked last so we don't auto-assign the boss to operator
        # checklists.
        role_target = template.role_target
        target_user = (
            await self._session.execute(
                select(User)
                .where(User.organization_id == template.organization_id)
                .where(User.is_active.is_(True))
                .where(User.role == role_target)
                .limit(1)
            )
        ).scalar_one_or_none()
        if target_user is not None:
            return target_user.id

        # Nothing matches the role_target → fall back to any active owner.
        owner = (
            await self._session.execute(
                select(User)
                .where(User.organization_id == template.organization_id)
                .where(User.is_active.is_(True))
                .where(User.role == UserRole.OWNER.value)
                .limit(1)
            )
        ).scalar_one_or_none()
        return owner.id if owner else None


__all__ = ["CreateRecurringShiftsTickUseCase", "TickReport"]
