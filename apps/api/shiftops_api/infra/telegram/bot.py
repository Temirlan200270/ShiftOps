"""Aiogram 3 bot: dispatcher, handlers, and update entrypoint.

The webhook handler in `api.v1.telegram` calls `dispatch_update(payload)`
which feeds raw JSON into the aiogram dispatcher. We do not use
aiogram's built-in webhook server because the FastAPI app already terminates
TLS and we want one process boundary.

Handlers we implement here are the *minimum* needed for V0:

- `/start` — greet, store/update telegram_account → user binding (deep links
  for tenant on-boarding land here as `/start <token>`).
- `/help` — short usage primer.
- callback queries with `waiver:<task_id>:approve|reject` — the same routes
  used by `dispatch_waiver_request`. We re-use the existing
  `ApproveWaiverUseCase` so business logic stays in the application layer.

Everything else (analytics, /shift commands, …) is V1 work; we keep the
dispatcher modular so we can add routers without touching this file.
"""

from __future__ import annotations

import logging
import uuid

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, Update
from sqlalchemy import select

from shiftops_api.application.shifts.approve_waiver import ApproveWaiverUseCase
from shiftops_api.config import get_settings
from shiftops_api.domain.result import Failure
from shiftops_api.infra.db.engine import get_sessionmaker
from shiftops_api.infra.db.models import TelegramAccount, User

_log = logging.getLogger(__name__)
_router = Router(name="shiftops.bot")


def _bot() -> Bot:
    return Bot(
        token=get_settings().tg_bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


@_router.message(Command("start"))
async def handle_start(message: Message) -> None:
    factory = get_sessionmaker()
    async with factory() as session:
        if message.from_user is None:
            return
        existing = await session.execute(
            select(TelegramAccount, User)
            .join(User, User.id == TelegramAccount.user_id)
            .where(TelegramAccount.tg_user_id == message.from_user.id)
        )
        row = existing.first()
        if row is None:
            web_app_url = get_settings().web_public_url
            await message.answer(
                "👋 Добро пожаловать в <b>ShiftOps</b>.\n\n"
                "Чтобы начать, попросите администратора добавить вас в систему "
                "и затем откройте приложение через кнопку.\n\n"
                f"🌐 Web App: {web_app_url}",
            )
            return
        _, user = row
        await message.answer(
            f"С возвращением, {user.full_name}. Откройте Web App, чтобы начать смену."
        )


@_router.message(Command("help"))
async def handle_help(message: Message) -> None:
    await message.answer(
        "<b>ShiftOps</b> помогает вести смены и контроль чек-листов.\n\n"
        "• /start — войти / привязать аккаунт.\n"
        "• Открыть Web App — список задач смены.\n"
        "• Уведомления о ваших сменах будут приходить сюда."
    )


@_router.callback_query(lambda c: (c.data or "").startswith("waiver:"))
async def handle_waiver_callback(callback: CallbackQuery) -> None:
    if not callback.data or not callback.from_user:
        await callback.answer("invalid", show_alert=False)
        return

    try:
        _, task_id_raw, decision = callback.data.split(":", 2)
        task_id = uuid.UUID(task_id_raw)
    except (ValueError, AttributeError):
        await callback.answer("malformed callback", show_alert=False)
        return

    if decision not in {"approve", "reject"}:
        await callback.answer("unknown decision", show_alert=False)
        return

    factory = get_sessionmaker()
    async with factory() as session:
        actor = (
            await session.execute(
                select(User)
                .join(TelegramAccount, TelegramAccount.user_id == User.id)
                .where(TelegramAccount.tg_user_id == callback.from_user.id)
                .where(User.role.in_(("owner", "admin")))
            )
        ).scalar_one_or_none()
        if actor is None:
            await callback.answer("у вас нет прав на это решение", show_alert=True)
            return

        use_case = ApproveWaiverUseCase(session=session)
        result = await use_case.execute(
            task_id=task_id,
            admin_user_id=actor.id,
            decision=decision,
        )
        if isinstance(result, Failure):
            _log.warning("waiver.callback.failed", extra={"err": result.error.code})
            await callback.answer(
                f"ошибка: {result.error.code}",
                show_alert=True,
            )
            return

    suffix = "одобрен" if decision == "approve" else "отклонён"
    await callback.answer(f"Waiver {suffix}", show_alert=False)
    if callback.message is not None:
        with_decision = callback.message.html_text + f"\n\n<i>→ {suffix} вами.</i>"
        try:
            await callback.message.edit_text(with_decision)
        except Exception:  # noqa: BLE001 — best-effort edit
            pass


_dispatcher: Dispatcher | None = None


def _get_dispatcher() -> Dispatcher:
    global _dispatcher
    if _dispatcher is None:
        dp = Dispatcher()
        dp.include_router(_router)
        _dispatcher = dp
    return _dispatcher


async def dispatch_update(payload: dict[str, object]) -> None:
    """Feed a raw Telegram JSON update into the aiogram dispatcher.

    Why we instantiate `Bot` per update: aiogram's `Bot` holds an
    `aiohttp.ClientSession`, which must be closed in the same loop it was
    created in. Inside FastAPI's request handler we are guaranteed that loop,
    so we keep the helper stateless and `await bot.session.close()` afterwards.
    """
    bot = _bot()
    try:
        update = Update.model_validate(payload)
        await _get_dispatcher().feed_update(bot=bot, update=update)
    finally:
        await bot.session.close()
