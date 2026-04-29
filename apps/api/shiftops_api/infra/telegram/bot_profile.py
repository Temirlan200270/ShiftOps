"""Bot profile texts and command list registration.

Telegram shows ``setMyDescription`` *before* the user clicks Start in an empty
chat; ``setMyShortDescription`` shows in the bot's contact card.

Slash menu (``/`` autocomplete)
--------------------------------
Telegram only suggests commands that were registered with ``setMyCommands``.
We set a **minimal default** list for strangers, then on each ``/start`` and
``/help`` we push a **per-private-chat** list via ``BotCommandScopeChat`` so
super-admin, owner, admin, and line staff see different hints.

The in-message ``/help`` handler still carries the full prose — the slash
menu is a short reminder, not documentation.
"""

from __future__ import annotations

import logging
from enum import StrEnum

from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

_log = logging.getLogger(__name__)


class SlashMenuProfile(StrEnum):
    """Who is typing in this private chat — drives slash suggestions."""

    GUEST = "guest"
    SUPER_ADMIN = "super_admin"
    OWNER = "owner"
    ADMIN = "admin"
    LINE = "line"  # operator / bartender


BOT_DESCRIPTION = (
    "ShiftOps — оперативный контроль смен в HoReCa.\n\n"
    "Что внутри:\n"
    "• чек-листы открытия и закрытия смены с фото-доказательствами;\n"
    "• защита от подделок (anti-fake) и оценка качества смены;\n"
    "• роли: владелец, администратор, оператор, бармен;\n"
    "• приглашения сотрудников по одноразовой ссылке.\n\n"
    "Откройте Web App в этом боте, чтобы начать. Если у вас ещё нет инвайта — "
    "попросите владельца или администратора прислать ссылку."
)

BOT_SHORT_DESCRIPTION = (
    "Контроль смен в HoReCa: чек-листы, фото-доказательства, оценка качества."
)

# Shown until the user runs /start — keep tiny so random visitors do not see
# super-admin org tooling.
DEFAULT_COMMANDS: list[BotCommand] = [
    BotCommand(command="start", description="Открыть ShiftOps"),
    BotCommand(command="help", description="Справка и подсказки команд"),
]

GUEST_COMMANDS: list[BotCommand] = list(DEFAULT_COMMANDS)

LINE_COMMANDS: list[BotCommand] = list(DEFAULT_COMMANDS)

ADMIN_COMMANDS: list[BotCommand] = list(DEFAULT_COMMANDS)

OWNER_COMMANDS: list[BotCommand] = [
    BotCommand(command="start", description="Открыть ShiftOps"),
    BotCommand(command="help", description="Справка по командам"),
    BotCommand(command="team_list", description="Список команды"),
    BotCommand(
        command="set_role",
        description="/set_role @user admin|operator|bartender",
    ),
    BotCommand(command="remove_member", description="/remove_member @user"),
]

SUPER_ADMIN_COMMANDS: list[BotCommand] = [
    BotCommand(command="start", description="Открыть ShiftOps"),
    BotCommand(command="help", description="Справка по командам"),
    BotCommand(command="create_org", description="Новая организация"),
    BotCommand(
        command="org_invite",
        description="Инвайт: имя или UUID, роль, часы 1–168",
    ),
    BotCommand(command="org_set_owner", description="Владелец: org + tg_id"),
    BotCommand(command="org_set_role", description="Роль: org + tg_id + роль"),
    BotCommand(command="org_remove_member", description="Деактивировать: org + tg_id"),
    BotCommand(command="cancel", description="Отменить сценарий create_org"),
]


def _commands_for_profile(profile: SlashMenuProfile) -> list[BotCommand]:
    if profile is SlashMenuProfile.SUPER_ADMIN:
        return SUPER_ADMIN_COMMANDS
    if profile is SlashMenuProfile.OWNER:
        return OWNER_COMMANDS
    if profile is SlashMenuProfile.ADMIN:
        return ADMIN_COMMANDS
    if profile is SlashMenuProfile.LINE:
        return LINE_COMMANDS
    return GUEST_COMMANDS


async def configure_bot_profile(bot: Bot) -> None:
    """Idempotently push description / short description / default commands."""

    try:
        await bot.set_my_description(description=BOT_DESCRIPTION)
        await bot.set_my_short_description(short_description=BOT_SHORT_DESCRIPTION)
        await bot.set_my_commands(commands=DEFAULT_COMMANDS, scope=BotCommandScopeDefault())
        _log.info("bot_profile.configured")
    except Exception as exc:  # noqa: BLE001 — best-effort
        _log.warning("bot_profile.configure_failed", extra={"error": str(exc)})


async def push_slash_menu_for_private_chat(
    bot: Bot,
    *,
    chat_id: int,
    profile: SlashMenuProfile,
) -> None:
    """Refresh ``/`` autocomplete for this private chat (per Telegram user)."""

    try:
        await bot.set_my_commands(
            commands=_commands_for_profile(profile),
            scope=BotCommandScopeChat(chat_id=chat_id),
        )
        _log.info("bot_profile.slash_menu_pushed", extra={"chat_id": chat_id, "profile": profile.value})
    except Exception as exc:  # noqa: BLE001
        _log.warning("bot_profile.slash_menu_failed", extra={"error": str(exc), "chat_id": chat_id})


__all__ = [
    "BOT_DESCRIPTION",
    "BOT_SHORT_DESCRIPTION",
    "SlashMenuProfile",
    "configure_bot_profile",
    "push_slash_menu_for_private_chat",
]
