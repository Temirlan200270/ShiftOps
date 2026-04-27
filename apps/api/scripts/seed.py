"""Demo seed: 1 org, 1 location, 3 users, 2 templates, today's morning shift.

Idempotent — re-running it on a populated DB will be a no-op (we look up
seeded entities by their well-known UUIDs).

Why fixed UUIDs: lets the TWA dev session sign in deterministically and lets
us reference rows from manual SQL during pilots ("the operator with id …").

Run with::

    docker compose exec api python scripts/seed.py
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.infra.db.engine import get_engine, get_sessionmaker
from shiftops_api.infra.db.models import (
    Location,
    Organization,
    Shift,
    TaskInstance,
    TelegramAccount,
    Template,
    TemplateTask,
    User,
)

_ORG_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
_LOC_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
_OWNER_ID = uuid.UUID("33333333-3333-3333-3333-333333333331")
_ADMIN_ID = uuid.UUID("33333333-3333-3333-3333-333333333332")
_OP_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
_TPL_MORNING_ID = uuid.UUID("44444444-4444-4444-4444-444444444441")
_TPL_EVENING_ID = uuid.UUID("44444444-4444-4444-4444-444444444442")


async def _ensure_org(session: AsyncSession) -> None:
    existing = await session.get(Organization, _ORG_ID)
    if existing:
        return
    session.add(
        Organization(
            id=_ORG_ID,
            name="ShiftOps Demo Bar",
            plan="trial",
            is_active=True,
            trial_ends_at=datetime.now(tz=UTC) + timedelta(days=30),
        )
    )


async def _ensure_location(session: AsyncSession) -> None:
    existing = await session.get(Location, _LOC_ID)
    if existing:
        return
    session.add(
        Location(
            id=_LOC_ID,
            organization_id=_ORG_ID,
            name="Main bar",
            timezone="Europe/Moscow",
            tg_admin_chat_id=None,  # set during pilot setup
        )
    )


async def _ensure_users(session: AsyncSession) -> None:
    seeds: list[dict[str, object]] = [
        {"id": _OWNER_ID, "role": "owner", "full_name": "Demo Owner"},
        {"id": _ADMIN_ID, "role": "admin", "full_name": "Demo Admin"},
        {"id": _OP_ID, "role": "operator", "full_name": "Demo Operator"},
    ]
    for s in seeds:
        if await session.get(User, s["id"]):
            continue
        session.add(
            User(
                id=s["id"],
                organization_id=_ORG_ID,
                role=s["role"],
                full_name=s["full_name"],
                locale="ru",
                is_active=True,
            )
        )


async def _ensure_telegram_accounts(session: AsyncSession) -> None:
    """We don't bind real TG ids in seed — those are filled when each user
    presses /start in the bot. We DO seed placeholder rows for tests so
    auth-related queries don't hit empty joins.

    Placeholder TG ids are negative so they can't collide with real TG ids
    (Telegram never issues negative user ids).
    """
    pairs = [
        (-1, _OWNER_ID),
        (-2, _ADMIN_ID),
        (-3, _OP_ID),
    ]
    for tg_id, user_id in pairs:
        existing = (
            await session.execute(
                select(TelegramAccount).where(TelegramAccount.tg_user_id == tg_id)
            )
        ).scalar_one_or_none()
        if existing:
            continue
        session.add(
            TelegramAccount(
                tg_user_id=tg_id,
                user_id=user_id,
                tg_username=None,
                tg_language_code="ru",
            )
        )


async def _ensure_templates(session: AsyncSession) -> None:
    morning = await session.get(Template, _TPL_MORNING_ID)
    if morning is None:
        session.add(
            Template(
                id=_TPL_MORNING_ID,
                organization_id=_ORG_ID,
                name="Morning Shift",
                role_target="operator",
            )
        )
        session.add_all(
            [
                TemplateTask(
                    template_id=_TPL_MORNING_ID,
                    title="Открыть кассу и проверить остаток",
                    description="Сверьте сумму с журналом закрытия предыдущей смены.",
                    criticality="critical",
                    requires_photo=False,
                    requires_comment=False,
                    order_index=0,
                ),
                TemplateTask(
                    template_id=_TPL_MORNING_ID,
                    title="Фото чистоты бара",
                    description="Фото зоны бара со столешницей в кадре.",
                    criticality="critical",
                    requires_photo=True,
                    order_index=1,
                ),
                TemplateTask(
                    template_id=_TPL_MORNING_ID,
                    title="Запустить кофемашину",
                    criticality="required",
                    requires_photo=False,
                    order_index=2,
                ),
                TemplateTask(
                    template_id=_TPL_MORNING_ID,
                    title="Сделать заготовки сиропов",
                    criticality="required",
                    requires_photo=False,
                    order_index=3,
                ),
                TemplateTask(
                    template_id=_TPL_MORNING_ID,
                    title="Разместить рекламные стопперы",
                    criticality="optional",
                    order_index=4,
                ),
            ]
        )

    evening = await session.get(Template, _TPL_EVENING_ID)
    if evening is None:
        session.add(
            Template(
                id=_TPL_EVENING_ID,
                organization_id=_ORG_ID,
                name="Evening Shift",
                role_target="operator",
            )
        )
        session.add_all(
            [
                TemplateTask(
                    template_id=_TPL_EVENING_ID,
                    title="Снятие Z-отчёта",
                    criticality="critical",
                    requires_photo=True,
                    requires_comment=False,
                    order_index=0,
                ),
                TemplateTask(
                    template_id=_TPL_EVENING_ID,
                    title="Уборка зала",
                    criticality="required",
                    requires_photo=True,
                    order_index=1,
                ),
                TemplateTask(
                    template_id=_TPL_EVENING_ID,
                    title="Закрыть склад",
                    criticality="required",
                    requires_photo=False,
                    order_index=2,
                ),
                TemplateTask(
                    template_id=_TPL_EVENING_ID,
                    title="Поставить инкассатор",
                    criticality="optional",
                    requires_comment=True,
                    order_index=3,
                ),
            ]
        )


async def _ensure_today_shift(session: AsyncSession) -> None:
    """Schedule a Morning Shift starting in ~5 minutes — handy for demos."""
    today = datetime.now(tz=UTC).date()
    start = datetime.combine(today, datetime.min.time(), tzinfo=UTC) + timedelta(hours=8)
    end = start + timedelta(hours=8)

    existing = (
        await session.execute(
            select(Shift)
            .where(Shift.location_id == _LOC_ID)
            .where(Shift.scheduled_start == start)
            .where(Shift.template_id == _TPL_MORNING_ID)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return

    shift_id = uuid.uuid4()
    session.add(
        Shift(
            id=shift_id,
            organization_id=_ORG_ID,
            location_id=_LOC_ID,
            template_id=_TPL_MORNING_ID,
            operator_user_id=_OP_ID,
            scheduled_start=start,
            scheduled_end=end,
            status="scheduled",
        )
    )

    template_tasks = (
        await session.execute(
            select(TemplateTask)
            .where(TemplateTask.template_id == _TPL_MORNING_ID)
            .order_by(TemplateTask.order_index.asc())
        )
    ).scalars().all()
    for tt in template_tasks:
        session.add(
            TaskInstance(
                shift_id=shift_id,
                template_task_id=tt.id,
                status="pending",
            )
        )


async def main() -> None:
    factory = get_sessionmaker()
    async with factory() as session:
        # RLS policies require us to either be a service role OR have
        # `app.org_id` set; we set it explicitly so the seed bypasses
        # tenant-isolation constraints cleanly.
        await session.execute(text("SET LOCAL app.org_id = :oid"), {"oid": str(_ORG_ID)})
        await _ensure_org(session)
        await session.flush()
        await _ensure_location(session)
        await _ensure_users(session)
        await _ensure_telegram_accounts(session)
        await _ensure_templates(session)
        await _ensure_today_shift(session)
        await session.commit()
    await get_engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())
