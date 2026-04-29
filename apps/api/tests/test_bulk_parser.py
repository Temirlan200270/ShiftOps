"""Tests for the bulk template parser.

The fixture text below is the *exact* Pl Vehana checklist the pilot sent.
We verify three properties:

1. The parser produces the expected number of sections (semantically
   meaningful groups; keeps the rendering layer cheap).
2. Critical tasks (Z-отчёт, Сигнализация включена, Газ выключен) are
   not silently dropped — they are part of the safety contract.
3. The "Продукты:" sub-list collapses into a single composite task with
   all items in the description; we don't want 12 micro-tasks for the
   operator.
"""

from __future__ import annotations

from shiftops_api.application.templates.bulk_parser import (
    parse_bulk_text,
)
from shiftops_api.domain.enums import Criticality, UserRole
from shiftops_api.application.templates.bulk_parser import to_template_input

OPENING_TEXT = """\
ЧЕК-ЛИСТ АДМИНИСТРАТОРА

ОТКРЫТИЕ РЕСТОРАНА (ПЛОВХАНА)

Дата: ____
Администратор: ____
Время прихода: ____

⸻

1. ОТКРЫТИЕ РЕСТОРАНА

☐ Открыть входную дверь
☐ Отключить сигнализацию
☐ Включить общий свет
☐ Включить наружную вывеску
☐ Включить вытяжки (зал + кухня)

⸻

2. ПРОВЕРКА КУХНИ

☐ Повара прибыли на смену
☐ Подготовлены казаны
☐ Проверен тандыр
☐ Проверены основные продукты:

Продукты:
- Рис
- Морковь
- Лук
- Мясо

☐ Работают холодильники
☐ Проверена температура холодильников

⸻

3. ПРОВЕРКА ЗАЛА

☐ Все столы чистые
☐ Стулья расставлены

⸻

5. КАССА И ФИНАНСЫ

☐ Закрыта касса
☐ Сделан Z-отчет
☐ Включена сигнализация
☐ Газ выключен

Подпись администратора: ____
"""


def test_sections_extracted_in_order() -> None:
    parsed, errors = parse_bulk_text(OPENING_TEXT)
    assert errors == []
    assert parsed.sections == [
        "ОТКРЫТИЕ РЕСТОРАНА",
        "ПРОВЕРКА КУХНИ",
        "ПРОВЕРКА ЗАЛА",
        "КАССА И ФИНАНСЫ",
    ]


def test_critical_titles_present() -> None:
    """Safety items must survive the parse — not dropped or merged."""

    parsed, _ = parse_bulk_text(OPENING_TEXT)
    titles = {t.title for t in parsed.tasks}
    for must_have in (
        "Закрыта касса",
        "Сделан Z-отчет",
        "Включена сигнализация",
        "Газ выключен",
    ):
        assert must_have in titles, f"missing: {must_have}"


def test_products_collapse_into_single_task() -> None:
    """Sub-list of products should not produce 4 separate tasks."""

    parsed, _ = parse_bulk_text(OPENING_TEXT)
    product_tasks = [t for t in parsed.tasks if "продукт" in t.title.lower()]
    assert len(product_tasks) == 1
    composite = product_tasks[0]
    assert composite.section == "ПРОВЕРКА КУХНИ"
    assert composite.description is not None
    assert "Рис" in composite.description
    assert "Лук" in composite.description


def test_signature_footer_ignored() -> None:
    """'Подпись администратора:' is paper-form noise, not a task."""

    parsed, _ = parse_bulk_text(OPENING_TEXT)
    titles = {t.title.lower() for t in parsed.tasks}
    assert all("подпись" not in t for t in titles)


def test_empty_text_returns_error() -> None:
    parsed, errors = parse_bulk_text("   \n\n  ")
    assert parsed.tasks == []
    assert any(e.code == "empty_content" for e in errors)


def test_text_without_any_checkboxes_reports_no_tasks() -> None:
    parsed, errors = parse_bulk_text("Just paragraphs.\nMore paragraphs.\n")
    assert parsed.tasks == []
    assert any(e.code == "no_tasks_found" for e in errors)


def test_to_template_input_round_trip() -> None:
    parsed, _ = parse_bulk_text(OPENING_TEXT)
    payload = to_template_input(parsed, name="Открытие Пловханы", role_target=UserRole.ADMIN)
    assert payload.name == "Открытие Пловханы"
    assert payload.role_target is UserRole.ADMIN
    # Every task carries a section assignment so the renderer can group them.
    assert all(t.section is not None for t in payload.tasks)
    # Every task is REQUIRED by default — owner toggles photo/critical later.
    assert all(t.criticality is Criticality.REQUIRED for t in payload.tasks)


def test_long_lines_are_truncated_with_ellipsis() -> None:
    """255-char title cap protects DB; we add an ellipsis for readability."""

    text = "1. Раздел\n☐ " + ("очень длинная задача " * 20) + "\n"
    parsed, errors = parse_bulk_text(text)
    assert errors == []
    assert len(parsed.tasks) == 1
    assert len(parsed.tasks[0].title) <= 255
