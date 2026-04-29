"""Plain-text checklist parser for the "Import from text" feature.

The owner pastes the same Markdown-ish format people already use for
HoReCa checklists: numbered or ``##`` headings as section names, and
``☐ ``/``- [ ] ``/``- [x] `` lines as tasks. We convert that into a
``TemplateInputDTO`` so the existing ``SaveTemplateUseCase`` can do the
heavy lifting (validation, audit, RLS).

Why a single-pass line scanner (no PEG, no markdown lib)
--------------------------------------------------------
The grammar is *tiny* — five rules, all anchored at the start of a
trimmed line. A line scanner is ~80 LoC, the dependency footprint is
zero, and the failure modes are obvious to read in tests. We
intentionally keep the parser strictly local: each line decides its own
role based on the most recent section header. There is no lookahead.

Sub-headings like ``Продукты:`` (a "list of products" inside a section)
collapse into a single task because rendering 12 individual checkboxes
for "Рис, Лук, Морковь" is hostile UX on a phone — the operator wants
"Проверить продукты" with the list as a description.

Heuristics for criticality / requires_photo
-------------------------------------------
We do not try to be clever: every parsed task is ``required`` with no
photo / comment requirement. Owners that want photos toggle the row
in the editor afterwards. The bulk-importer is a *bootstrap*, not a
rules engine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from shiftops_api.application.templates.dtos import (
    TemplateInputDTO,
    TemplateTaskInputDTO,
)
from shiftops_api.domain.enums import Criticality, UserRole

# Numbered section: "1. ОТКРЫТИЕ" / "2. КОНТРОЛЬ КУХНИ".
_SECTION_NUMBERED = re.compile(r"^\s*\d+\s*[.)]\s+(?P<title>.+?)\s*$")
# Markdown-ish heading: "## Кухня", "### Кухня".
_SECTION_HASH = re.compile(r"^\s*#{2,6}\s+(?P<title>.+?)\s*$")
# A task line: "☐ Открыть дверь", "- [ ] Открыть дверь", "* [ ] Открыть".
_TASK_BOX = re.compile(r"^\s*(?:[*\-]\s*)?(?:☐|☑|☒|\[ \]|\[x\]|\[X\])\s+(?P<title>.+?)\s*$")
# Some users write "- Открыть дверь" without a checkbox. We also accept
# bullet lines ONLY when we are inside a section, otherwise we'd swallow
# the document title. Numbered lines like "1. Open" are NOT tasks here —
# they are section headings (handled above).
_TASK_BULLET = re.compile(r"^\s*[*\-]\s+(?P<title>.+?)\s*$")
# A "list intro" line that promises a list of items below: "Продукты:".
_LIST_INTRO = re.compile(r"^\s*(?P<title>[^\s:].{0,62})\s*:\s*$")

# Ignore footer noise the user often pastes ("Подпись администратора:").
_IGNORED_PREFIXES = (
    "подпись",
    "дата:",
    "администратор:",
    "время прихода",
    "время закрытия",
)

_SEPARATOR_LINE = re.compile(r"^\s*[-=⸻—_]{2,}\s*$")

_MAX_TITLE = 255
_MIN_TITLE = 3
_MAX_DESCRIPTION = 2000
_MAX_TASKS = 200


@dataclass(frozen=True, slots=True)
class ParsedTemplate:
    """The parser's output. Convertible to ``TemplateInputDTO`` once the
    caller decided on a name + role.
    """

    sections: list[str]
    tasks: list[TemplateTaskInputDTO]


@dataclass(frozen=True, slots=True)
class BulkParseError:
    code: str  # stable string for i18n: e.g. "no_tasks_found", "too_many_tasks"
    message: str = ""


def parse_bulk_text(content: str) -> tuple[ParsedTemplate, list[BulkParseError]]:
    """Parse ``content`` into a ``ParsedTemplate``.

    The function never raises — invalid inputs come back as a list of
    ``BulkParseError`` so the HTTP layer can render a structured error.
    The first ``ParsedTemplate`` is always returned, even on errors, so
    a "preview with warnings" UI flow stays simple.
    """

    if not content or not content.strip():
        return ParsedTemplate(sections=[], tasks=[]), [
            BulkParseError(code="empty_content", message="provide checklist text")
        ]

    tasks: list[TemplateTaskInputDTO] = []
    sections: list[str] = []
    current_section: str | None = None
    pending_list_title: str | None = None
    pending_list_items: list[str] = []
    errors: list[BulkParseError] = []

    def flush_pending_list() -> None:
        nonlocal pending_list_title, pending_list_items
        if pending_list_title is None or not pending_list_items:
            pending_list_title = None
            pending_list_items = []
            return
        title = _truncate_title(f"Проверить: {pending_list_title.lower()}")
        description = "\n".join(f"• {item}" for item in pending_list_items)[:_MAX_DESCRIPTION]
        tasks.append(
            TemplateTaskInputDTO(
                title=title,
                description=description,
                section=current_section,
                criticality=Criticality.REQUIRED,
                requires_photo=False,
                requires_comment=False,
            )
        )
        pending_list_title = None
        pending_list_items = []

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or _SEPARATOR_LINE.match(line):
            flush_pending_list()
            continue

        # Skip explicit ignored prefixes ("Подпись администратора:" etc).
        lowered = line.lower()
        if any(lowered.startswith(prefix) for prefix in _IGNORED_PREFIXES):
            flush_pending_list()
            continue

        # Section heading wins over everything else.
        section_match = _SECTION_NUMBERED.match(line) or _SECTION_HASH.match(line)
        if section_match:
            flush_pending_list()
            current_section = _truncate_section(section_match.group("title"))
            if current_section and current_section not in sections:
                sections.append(current_section)
            continue

        # Task with explicit checkbox.
        task_match = _TASK_BOX.match(line)
        if task_match:
            flush_pending_list()
            title = task_match.group("title")
            # "☐ Foo:" is treated as a list intro: the operator wrote
            # the checkbox as a header for an inline bullet list. We
            # don't want both a task "Foo:" *and* a synthesised
            # composite "Проверить: foo" — collapse to the latter so
            # the operator sees one row, not two.
            if title.rstrip().endswith(":") and current_section is not None:
                pending_list_title = title.rstrip().rstrip(":").strip()
                pending_list_items = []
                continue
            _append_task(tasks, title, current_section, errors)
            continue

        # "Продукты:" — promise of a list of items below.
        list_intro = _LIST_INTRO.match(line)
        if list_intro and current_section is not None:
            flush_pending_list()
            pending_list_title = list_intro.group("title").strip()
            continue

        # Bullet lines AFTER a list intro become items of that intro.
        bullet_match = _TASK_BULLET.match(line)
        if bullet_match and pending_list_title is not None:
            pending_list_items.append(bullet_match.group("title").strip())
            continue

        # Bullet lines without a list intro become standalone tasks if
        # we are inside a section (typical for "- Wipe counters").
        if bullet_match and current_section is not None:
            _append_task(tasks, bullet_match.group("title"), current_section, errors)
            continue

    flush_pending_list()

    if not tasks:
        errors.append(
            BulkParseError(code="no_tasks_found", message="parser found no checkbox lines")
        )
    elif len(tasks) > _MAX_TASKS:
        errors.append(
            BulkParseError(
                code="too_many_tasks",
                message=f"got {len(tasks)} tasks; limit is {_MAX_TASKS}",
            )
        )

    return ParsedTemplate(sections=sections, tasks=tasks), errors


def to_template_input(
    parsed: ParsedTemplate,
    *,
    name: str,
    role_target: UserRole,
) -> TemplateInputDTO:
    """Wrap a ``ParsedTemplate`` in a ``TemplateInputDTO`` ready for
    ``SaveTemplateUseCase``. The caller is responsible for clipping the
    task list if the parser flagged it as oversized.
    """

    return TemplateInputDTO(
        name=name,
        role_target=role_target,
        tasks=list(parsed.tasks),
    )


def _append_task(
    tasks: list[TemplateTaskInputDTO],
    raw_title: str,
    section: str | None,
    errors: list[BulkParseError],
) -> None:
    title = _truncate_title(raw_title.strip())
    if len(title) < _MIN_TITLE:
        errors.append(
            BulkParseError(
                code="task_title_too_short",
                message=f"task title '{raw_title!s}' is shorter than {_MIN_TITLE} chars",
            )
        )
        return
    tasks.append(
        TemplateTaskInputDTO(
            title=title,
            description=None,
            section=section,
            criticality=Criticality.REQUIRED,
            requires_photo=False,
            requires_comment=False,
        )
    )


def _truncate_title(title: str) -> str:
    if len(title) <= _MAX_TITLE:
        return title
    return title[: _MAX_TITLE - 1].rstrip() + "…"


def _truncate_section(title: str) -> str:
    title = title.strip().rstrip(":.")
    if len(title) <= 64:
        return title
    return title[:63].rstrip() + "…"


__all__ = [
    "BulkParseError",
    "ParsedTemplate",
    "parse_bulk_text",
    "to_template_input",
]
