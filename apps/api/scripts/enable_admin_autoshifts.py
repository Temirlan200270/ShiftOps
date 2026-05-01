"""Enable daily admin autoshifts for an existing organization.

What this script does (idempotent):
1) Resolves admin user by Telegram id inside the target org.
2) Ensures at least one location exists (creates one when missing).
3) Attaches recurrence JSON to "Открытие ресторана" / "Закрытие ресторана"
   templates (role_target=admin).
4) Runs one synthetic recurring tick at opening time for *today* so the admin
   immediately gets a checklist in ``/v1/shifts/me``.

Run in prod container:

    python -m scripts.enable_admin_autoshifts \
      --org-id <uuid> \
      --tg-user-id <int>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.templates.recurring_shifts_tick import (
    CreateRecurringShiftsTickUseCase,
)
from shiftops_api.infra.db.engine import get_engine, get_sessionmaker
from shiftops_api.infra.db.models import Location, Organization, TelegramAccount, Template, User

OPENING_TEMPLATE = "Открытие ресторана"
CLOSING_TEMPLATE = "Закрытие ресторана"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--org-id", type=uuid.UUID, required=True)
    p.add_argument("--tg-user-id", type=int, required=True)
    p.add_argument("--location-name", default="PlovХана Main")
    p.add_argument("--timezone", default="Asia/Almaty")
    return p


async def _resolve_admin_user(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    tg_user_id: int,
) -> User:
    row = (
        await session.execute(
            select(User)
            .join(TelegramAccount, TelegramAccount.user_id == User.id)
            .where(User.organization_id == org_id)
            .where(TelegramAccount.tg_user_id == tg_user_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        raise SystemExit(
            f"user not found for org={org_id} and tg_user_id={tg_user_id}",
        )
    return row


async def _ensure_location(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    location_name: str,
    timezone: str,
) -> Location:
    existing = (
        await session.execute(
            select(Location)
            .where(Location.organization_id == org_id)
            .order_by(Location.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    loc = Location(
        id=uuid.uuid4(),
        organization_id=org_id,
        name=location_name,
        timezone=timezone,
        tg_admin_chat_id=None,
    )
    session.add(loc)
    await session.flush()
    return loc


def _recurrence_blob(
    *,
    location_id: uuid.UUID,
    timezone: str,
    assignee_id: uuid.UUID,
    time_of_day: time,
    duration_min: int,
) -> str:
    payload = {
        "kind": "daily",
        "auto_create": True,
        "time_of_day": time_of_day.strftime("%H:%M"),
        "duration_min": duration_min,
        "weekdays": [1, 2, 3, 4, 5, 6, 7],
        "timezone": timezone,
        "location_id": str(location_id),
        "default_assignee_id": str(assignee_id),
        "lead_time_min": 30,
    }
    return json.dumps(payload, ensure_ascii=False)


async def _apply_recurrence(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    location: Location,
    assignee_id: uuid.UUID,
) -> None:
    templates = (
        await session.execute(
            select(Template)
            .where(Template.organization_id == org_id)
            .where(Template.role_target == "admin")
            .where(Template.name.in_([OPENING_TEMPLATE, CLOSING_TEMPLATE]))
        )
    ).scalars().all()
    if not templates:
        raise SystemExit(
            "admin templates not found (expected opening/closing templates to exist)",
        )

    by_name = {tpl.name: tpl for tpl in templates}
    missing = [n for n in (OPENING_TEMPLATE, CLOSING_TEMPLATE) if n not in by_name]
    if missing:
        raise SystemExit(f"missing templates: {missing}")

    opening_blob = _recurrence_blob(
        location_id=location.id,
        timezone=location.timezone or "UTC",
        assignee_id=assignee_id,
        time_of_day=time(9, 0),
        duration_min=8 * 60,
    )
    closing_blob = _recurrence_blob(
        location_id=location.id,
        timezone=location.timezone or "UTC",
        assignee_id=assignee_id,
        time_of_day=time(23, 0),
        duration_min=4 * 60,
    )

    await session.execute(
        text("UPDATE templates SET default_schedule = CAST(:blob AS jsonb) WHERE id = :id"),
        {"blob": opening_blob, "id": by_name[OPENING_TEMPLATE].id},
    )
    await session.execute(
        text("UPDATE templates SET default_schedule = CAST(:blob AS jsonb) WHERE id = :id"),
        {"blob": closing_blob, "id": by_name[CLOSING_TEMPLATE].id},
    )

    print("opening_template_id", by_name[OPENING_TEMPLATE].id)
    print("closing_template_id", by_name[CLOSING_TEMPLATE].id)


async def main() -> None:
    args = _parser().parse_args()
    sm = get_sessionmaker()

    async with sm() as session:
        org = await session.get(Organization, args.org_id)
        if org is None:
            raise SystemExit(f"organization not found: {args.org_id}")

        await session.execute(
            text("SELECT set_config('app.org_id', :oid, true)"),
            {"oid": str(args.org_id)},
        )

        user = await _resolve_admin_user(
            session,
            org_id=args.org_id,
            tg_user_id=args.tg_user_id,
        )
        location = await _ensure_location(
            session,
            org_id=args.org_id,
            location_name=args.location_name,
            timezone=args.timezone,
        )
        await _apply_recurrence(
            session,
            org_id=args.org_id,
            location=location,
            assignee_id=user.id,
        )
        await session.commit()

        # Materialize "today opening shift" immediately so /v1/shifts/me is not empty.
        try:
            tz = ZoneInfo(location.timezone or "UTC")
        except Exception:
            tz = ZoneInfo("UTC")
        now_local_opening = datetime.combine(datetime.now(tz).date(), time(9, 0), tzinfo=tz)
        tick = CreateRecurringShiftsTickUseCase(
            session=session,
            now=now_local_opening.astimezone(UTC),
        )
        report = await tick.execute()
        await session.commit()

        print("org", org.id, org.name)
        print("user_id", user.id, "role", user.role, "active", user.is_active)
        print("location_id", location.id, "location_name", location.name, "tz", location.timezone)
        print(
            "tick_inspected",
            report.inspected,
            "tick_created",
            report.created,
            "tick_aborted_expired_vacant",
            report.aborted_expired_vacant,
        )

    await get_engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())
