"""Seed two checklist templates ("Открытие" / "Закрытие") for the
PlovХана pilot organisation.

Why a separate script instead of the generic ``scripts/seed.py``
----------------------------------------------------------------
The generic seed paints a *demo* org. PlovХана is a real customer
running on prod data — we want the script to:

1. Look up the existing organisation by name (or accept an explicit
   ``--org-id``) — never auto-create.
2. Create two templates idempotently. If a template with the target
   name exists already, we update its tasks in place so re-runs heal
   any drift.
3. Mark a small set of tasks as ``critical`` and ``requires_photo``
   based on what "must not slip" semantics actually mean in the
   restaurant — not via heuristics inside the bulk parser.
4. Optionally arm ``default_schedule`` so the cron tick generates a
   shift every day at 09:00 (open) and 23:00 (close).

Usage::

    docker compose exec api python -m scripts.seed_plovkhana_templates \\
        --org-name "PlovХана"

Optional flags::

    --location-name "<name>"   pin the recurrence to a specific location
    --opening-assignee <uuid>  default operator/admin for the morning shift
    --closing-assignee <uuid>  default operator/admin for the evening shift
    --no-recurrence            create templates without enabling auto-create

Run as a one-off after the org owner is already linked to Telegram.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import time

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.templates.bulk_parser import parse_bulk_text
from shiftops_api.application.templates.recurrence import RecurrenceConfig
from shiftops_api.domain.enums import Criticality
from shiftops_api.infra.db.engine import get_engine, get_sessionmaker
from shiftops_api.infra.db.models import (
    Location,
    Organization,
    Template,
    TemplateTask,
)

_log = logging.getLogger("seed.plovkhana")


# -- Curated checklist text ---------------------------------------------------
# Сбалансировано: ~36 задач на открытие, ~24 на закрытие. Микро-задачи
# (бумага/мыло/полотенца) — в описании одной задачи "Подготовка туалета".

OPENING_TEXT = """\
1. ОТКРЫТИЕ РЕСТОРАНА

☐ Открыть входную дверь
☐ Отключить сигнализацию
☐ Включить общий свет в зале и коридорах
☐ Включить наружную вывеску
☐ Включить вытяжки на кухне и в зале
☐ Открыть кассу с разменом
☐ Проверить, что кассовый аппарат печатает чек

2. КУХНЯ

☐ Повара прибыли на смену
☐ Включён холодильник, температура в норме
☐ Проверить морозильную камеру
☐ Подготовлены казаны
☐ Проверить тандыр
☐ Проверить плиту и газ (нет утечек)
☐ Проверены основные продукты

Продукты:
- Рис
- Морковь
- Лук
- Мясо
- Специи и приправы

☐ Чистота кухни (фото после уборки)
☐ Подготовлена посуда и приборы
☐ Подготовлены пакеты для доставки

3. ЗАЛ И БАР

☐ Все столы протёрты
☐ Стулья расставлены ровно
☐ Меню разложены на столах
☐ Чайники чистые и вымыты
☐ Кофемашина включена и очищена
☐ Музыка включена на нормальной громкости
☐ Кондиционер выставлен на 22°C

4. ТУАЛЕТЫ

☐ Туалеты чистые и вымыты (фото)
☐ Подготовлены расходники: бумага, мыло, полотенца, освежитель

5. ПЕРСОНАЛ

☐ Все официанты в форме и опрятны
☐ Бейджи на сотрудниках
☐ Проведён мини-брифинг (новости дня, акции, стоп-лист)

6. ПРЕДОТКРЫТИЕ

☐ Стоп-лист обновлён
☐ Терминал безналичной оплаты включён и работает
☐ Wi-Fi и интернет работают
☐ Открыть для гостей
"""

CLOSING_TEXT = """\
1. ЗАЛ И БАР

☐ Все гости ушли
☐ Все столы убраны и протёрты
☐ Стулья поставлены на столы (если положено)
☐ Полы вымыты
☐ Кофемашина очищена и выключена
☐ Чайники вымыты и убраны

2. КУХНЯ

☐ Все продукты убраны в холодильник
☐ Поверхности и плиты вымыты
☐ Чистота кухни (фото после уборки)
☐ Холодильник закрыт, температура в норме
☐ Морозильник закрыт, температура в норме
☐ Газ выключен
☐ Вытяжки выключены

3. ТУАЛЕТЫ И ЗОНЫ ОБЩЕГО ПОЛЬЗОВАНИЯ

☐ Туалеты убраны (фото)
☐ Расходники проверены на завтра

4. КАССА И ФИНАНСЫ

☐ Z-отчёт снят (фото)
☐ Деньги пересчитаны и положены в сейф
☐ Касса закрыта на ключ

5. ЗАКРЫТИЕ

☐ Свет в зале выключен
☐ Кондиционеры выключены
☐ Музыка выключена
☐ Вывеска выключена
☐ Закрыта входная дверь
☐ Сигнализация включена (фото)
"""

# -- Critical / photo overrides -----------------------------------------------
# Имена должны точно совпадать с тем, что генерирует парсер.

PHOTO_REQUIRED = {
    "Чистота кухни (фото после уборки)",
    "Туалеты чистые и вымыты (фото)",
    "Туалеты убраны (фото)",
    "Z-отчёт снят (фото)",
    "Сигнализация включена (фото)",
}

CRITICAL = {
    "Газ выключен",
    "Сигнализация включена (фото)",
    "Закрыта входная дверь",
    "Открыть кассу с разменом",
    "Z-отчёт снят (фото)",
}


@dataclass(frozen=True, slots=True)
class _Args:
    org_name: str | None
    org_id: uuid.UUID | None
    location_name: str | None
    opening_assignee: uuid.UUID | None
    closing_assignee: uuid.UUID | None
    no_recurrence: bool


def _parse_args(argv: Sequence[str] | None = None) -> _Args:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org-name", default="PlovХана")
    parser.add_argument("--org-id", type=uuid.UUID)
    parser.add_argument("--location-name", default=None)
    parser.add_argument("--opening-assignee", type=uuid.UUID, default=None)
    parser.add_argument("--closing-assignee", type=uuid.UUID, default=None)
    parser.add_argument("--no-recurrence", action="store_true")
    ns = parser.parse_args(argv)
    return _Args(
        org_name=ns.org_name,
        org_id=ns.org_id,
        location_name=ns.location_name,
        opening_assignee=ns.opening_assignee,
        closing_assignee=ns.closing_assignee,
        no_recurrence=ns.no_recurrence,
    )


async def _resolve_org(session: AsyncSession, args: _Args) -> Organization:
    if args.org_id is not None:
        org = await session.get(Organization, args.org_id)
        if org is None:
            raise SystemExit(f"organization not found: {args.org_id}")
        return org

    name = (args.org_name or "").strip()
    if not name:
        raise SystemExit("either --org-name or --org-id is required")

    org = (
        await session.execute(
            select(Organization).where(Organization.name == name)
        )
    ).scalar_one_or_none()
    if org is None:
        raise SystemExit(f"organization not found by name: {name!r}")
    return org


async def _resolve_location(
    session: AsyncSession, org: Organization, args: _Args
) -> Location | None:
    if args.location_name is not None:
        row = (
            await session.execute(
                select(Location)
                .where(Location.organization_id == org.id)
                .where(Location.name == args.location_name)
            )
        ).scalar_one_or_none()
        if row is None:
            raise SystemExit(
                f"location {args.location_name!r} not found in org {org.name!r}",
            )
        return row

    rows = (
        await session.execute(
            select(Location)
            .where(Location.organization_id == org.id)
            .order_by(Location.name.asc())
        )
    ).scalars().all()
    if not rows:
        _log.warning(
            "no locations in org — recurrence will not be configured",
        )
        return None
    if len(rows) > 1:
        _log.info(
            "multiple locations — picking first by name; pass --location-name to pin",
        )
    return rows[0]


def _apply_overrides(tasks: list[TemplateTask]) -> None:
    for task in tasks:
        if task.title in PHOTO_REQUIRED:
            task.requires_photo = True
        if task.title in CRITICAL:
            task.criticality = Criticality.CRITICAL.value


async def _upsert_template(
    session: AsyncSession,
    org: Organization,
    *,
    name: str,
    role_target: str,
    content: str,
    recurrence: RecurrenceConfig | None,
) -> Template:
    existing = (
        await session.execute(
            select(Template)
            .where(Template.organization_id == org.id)
            .where(Template.name == name)
        )
    ).scalar_one_or_none()

    parsed, errors = parse_bulk_text(content)
    if errors:
        _log.warning("parser warnings for %s: %s", name, [e.code for e in errors])
    if not parsed.tasks:
        raise SystemExit(f"failed to parse template {name!r}")

    if existing is None:
        tpl = Template(
            organization_id=org.id,
            name=name,
            role_target=role_target,
        )
        session.add(tpl)
        await session.flush()
    else:
        tpl = existing
        tpl.role_target = role_target
        # Wipe existing tasks; the bulk-import flow is the canonical
        # source for this template.
        for old in (
            await session.execute(
                select(TemplateTask).where(TemplateTask.template_id == tpl.id)
            )
        ).scalars():
            await session.delete(old)
        await session.flush()

    new_tasks: list[TemplateTask] = []
    for index, task in enumerate(parsed.tasks):
        row = TemplateTask(
            template_id=tpl.id,
            title=task.title,
            description=task.description,
            section=task.section,
            criticality=task.criticality.value,
            requires_photo=task.requires_photo,
            requires_comment=task.requires_comment,
            order_index=index,
        )
        new_tasks.append(row)
        session.add(row)
    _apply_overrides(new_tasks)

    tpl.default_schedule = recurrence.to_storage() if recurrence else None
    await session.flush()
    return tpl


def _build_recurrence(
    *,
    location: Location,
    time_of_day: time,
    duration_min: int,
    assignee: uuid.UUID | None,
) -> RecurrenceConfig:
    return RecurrenceConfig(
        kind="daily",
        auto_create=True,
        time_of_day=time_of_day,
        duration_min=duration_min,
        weekdays=[1, 2, 3, 4, 5, 6, 7],
        timezone=location.timezone or "UTC",
        location_id=location.id,
        default_assignee_id=assignee,
        lead_time_min=30,
    )


async def main(argv: Sequence[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = _parse_args(argv)

    factory = get_sessionmaker()
    async with factory() as session:
        org = await _resolve_org(session, args)

        # Set the RLS GUC so subsequent inserts/updates pass the policy.
        await session.execute(
            text("SELECT set_config('app.org_id', :oid, true)"),
            {"oid": str(org.id)},
        )

        location = (
            None
            if args.no_recurrence
            else await _resolve_location(session, org, args)
        )

        opening_recurrence = (
            _build_recurrence(
                location=location,
                time_of_day=time(9, 0),
                duration_min=8 * 60,
                assignee=args.opening_assignee,
            )
            if location is not None
            else None
        )
        closing_recurrence = (
            _build_recurrence(
                location=location,
                time_of_day=time(23, 0),
                duration_min=4 * 60,
                assignee=args.closing_assignee,
            )
            if location is not None
            else None
        )

        opening = await _upsert_template(
            session,
            org,
            name="Открытие ресторана",
            role_target="admin",
            content=OPENING_TEXT,
            recurrence=opening_recurrence,
        )
        closing = await _upsert_template(
            session,
            org,
            name="Закрытие ресторана",
            role_target="admin",
            content=CLOSING_TEXT,
            recurrence=closing_recurrence,
        )

        await session.commit()
        _log.info("seeded org %s (%s)", org.name, org.id)
        _log.info("template opening: %s", opening.id)
        _log.info("template closing: %s", closing.id)

    await get_engine().dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main(sys.argv[1:]))
    except SystemExit as exc:
        _log.error("seed.failed: %s", exc)
        raise
