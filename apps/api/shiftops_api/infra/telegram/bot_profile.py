"""Bot profile texts and command list registration.

Telegram shows ``setMyDescription`` *before* the user clicks Start in an empty
chat; ``setMyShortDescription`` shows in the bot's contact card. Commands set
via ``setMyCommands`` populate the slash-menu suggestions.

We register the same baseline command list for everyone, then the in-message
``/help`` handler tailors the contents per role (super-admin gets extra org
commands, owner gets team-management hints, operator gets the lean one).
"""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import BotCommand

_log = logging.getLogger(__name__)

BOT_DESCRIPTION = (
    "ShiftOps — оперативный контроль смен в HoReCa.\n\n"
    "Что внутри:\n"
    "• чек-листы открытия и закрытия смены с фото-доказательствами;\n"
    "• защита от подделок (anti-fake) и оценка качества смены;\n"
    "• роли: владелец, администратор, оператор;\n"
    "• приглашения сотрудников по одноразовой ссылке.\n\n"
    "Откройте Web App в этом боте, чтобы начать. Если у вас ещё нет инвайта — "
    "попросите владельца или администратора прислать ссылку."
)

BOT_SHORT_DESCRIPTION = (
    "Контроль смен в HoReCa: чек-листы, фото-доказательства, оценка качества."
)

BASE_COMMANDS: list[BotCommand] = [
    BotCommand(command="start", description="Открыть ShiftOps"),
    BotCommand(command="help", description="Справка по командам"),
    BotCommand(command="team_list", description="Список команды (для владельца)"),
    BotCommand(
        command="set_role",
        description="Сменить роль (для владельца): /set_role @user admin|operator",
    ),
    BotCommand(
        command="remove_member",
        description="Удалить участника (для владельца): /remove_member @user",
    ),
]


async def configure_bot_profile(bot: Bot) -> None:
    """Idempotently push description / short description / commands.

    Failures are logged and swallowed: we don't want a Telegram outage to
    block API startup. The next deploy will re-attempt.
    """

    try:
        await bot.set_my_description(description=BOT_DESCRIPTION)
        await bot.set_my_short_description(short_description=BOT_SHORT_DESCRIPTION)
        await bot.set_my_commands(commands=BASE_COMMANDS)
        _log.info("bot_profile.configured")
    except Exception as exc:  # noqa: BLE001 — best-effort
        _log.warning("bot_profile.configure_failed", extra={"error": str(exc)})
