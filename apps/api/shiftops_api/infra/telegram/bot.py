"""Aiogram 3 bot: dispatcher, handlers, and update entrypoint.

The webhook handler in `api.v1.telegram` calls `dispatch_update(payload)`
which feeds raw JSON into the aiogram dispatcher. We do not use
aiogram's built-in webhook server because the FastAPI app already terminates
TLS and we want one process boundary.

Handlers we implement here are the *minimum* needed for V0:

- `/start` — greet, store/update telegram_account → user binding (deep links
  for tenant on-boarding land here as `/start inv_<token>`).
- `/help` — short usage primer.
- `inv_*` — redeem single-use org invite (see application.invites.redeem_invite).
- `/create_org` — super-admin FSM: org name, then owner Telegram id.
- callback queries with `waiver:<task_id>:approve|reject` — the same routes
  used by `dispatch_waiver_request`. We re-use the existing
  `ApproveWaiverUseCase` so business logic stays in the application layer.

Everything else (analytics, /shift commands, …) is V1 work; we keep the
dispatcher modular so we can add routers without touching this file.
"""

from __future__ import annotations

import logging
import uuid

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message, Update
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.invites.create_system_invite import CreateSystemInviteUseCase
from shiftops_api.application.invites.redeem_invite import RedeemInviteUseCase
from shiftops_api.application.organizations.create_organization import (
    CreateOrganizationUseCase,
)
from shiftops_api.application.shifts.approve_waiver import ApproveWaiverUseCase
from shiftops_api.config import get_settings
from shiftops_api.domain.result import Failure, Success
from shiftops_api.infra.db.engine import get_sessionmaker
from shiftops_api.infra.db.models import TelegramAccount, User

_log = logging.getLogger(__name__)
_router = Router(name="shiftops.bot")
_storage = MemoryStorage()


class CreateOrgFSM(StatesGroup):
    org_name = State()


def _bot() -> Bot:
    return Bot(
        token=get_settings().tg_bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def _start_payload(message: Message) -> str:
    if not message.text:
        return ""
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return ""
    return parts[1].strip()


@_router.message(Command("start"))
async def handle_start(message: Message) -> None:
    if message.from_user is None:
        return
    payload = _start_payload(message)
    factory = get_sessionmaker()
    async with factory() as session:
        existing = await _existing_tg_user(session, message.from_user.id)
        if payload.startswith("inv_"):
            token = payload.removeprefix("inv_").strip()
            if not token:
                await message.answer(
                    "Ссылка приглашения повреждена. Попросите новую у администратора."
                )
                return
            if existing is not None:
                await message.answer(
                    "Ваш Telegram уже привязан к ShiftOps — откройте Web App, инвайт не нужен."
                )
                return
            use_case = RedeemInviteUseCase(session)
            result = await use_case.execute(token=token, tg=message.from_user)
            if isinstance(result, Failure):
                messages = {
                    "invite_not_found": "Ссылка недействительна или устарела.",
                    "invite_expired": "Срок ссылки истёк. Попросите новую у администратора.",
                    "invite_already_used": "Эта ссылка уже использована.",
                    "organization_inactive": "Организация не активна. Обратитесь в поддержку.",
                }
                text = messages.get(
                    result.error.code,
                    "Не удалось принять приглашение. Попросите администратора выдать новую ссылку.",
                )
                await message.answer(text)
                await session.rollback()
                return
            assert isinstance(result, Success)
            loc_line = (
                f"Вас пригласили в точку: <b>{result.value.location_label}</b>.\n"
                if result.value.location_label
                else ""
            )
            await message.answer(
                f"✅ Добро пожаловать в <b>{result.value.organization_name}</b>.\n"
                f"{loc_line}"
                f"Ваша роль: <b>{result.value.role}</b>.\n"
                f"Теперь откройте Web App, чтобы начать."
            )
            await session.commit()
            return

        if existing is None:
            web_app_url = get_settings().web_public_url
            await message.answer(
                "👋 Добро пожаловать в <b>ShiftOps</b>.\n\n"
                "Чтобы начать, попросите администратора пригласить вас ссылкой "
                f"из приложения, затем откройте Web App.\n\n🌐 {web_app_url}",
            )
            return
        _, user = existing
        await message.answer(
            f"С возвращением, {user.full_name}. Откройте Web App, чтобы начать смену."
        )


async def _existing_tg_user(
    session: AsyncSession, tg_id: int
) -> tuple[TelegramAccount, User] | None:
    ex = await session.execute(
        select(TelegramAccount, User)
        .join(User, User.id == TelegramAccount.user_id)
        .where(TelegramAccount.tg_user_id == tg_id)
    )
    r = ex.first()
    if r is None:
        return None
    a, u = r
    return (a, u)


def _is_super_admin(user_id: int) -> bool:
    sid = get_settings().super_admin_tg_id
    return sid is not None and user_id == sid


@_router.message(Command("create_org"))
async def create_org_start(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    if not _is_super_admin(message.from_user.id):
        return
    await state.set_state(CreateOrgFSM.org_name)
    await message.answer(
        "Создаём новую организацию.\n"
        "Как <b>назовём</b> её? (одним сообщением, например <i>The Rusty Anchor</i>)\n"
        "Отмена: /cancel"
    )


@_router.message(
    StateFilter(CreateOrgFSM.org_name),
    F.text,
)
async def create_org_name(message: Message, state: FSMContext) -> None:
    if not message.text or not message.from_user or not _is_super_admin(message.from_user.id):
        return
    name = message.text.strip()
    if not name or len(name) < 2:
        await message.answer("Название слишком короткое. Повторите или /cancel")
        return
    factory = get_sessionmaker()
    async with factory() as session:
        uc = CreateOrganizationUseCase(session)
        r = await uc.execute(name=name)
        if isinstance(r, Failure):
            await message.answer(f"Ошибка: {r.error.code}. Повторите /create_org")
            await session.rollback()
            await state.clear()
            return
        assert isinstance(r, Success)
        await session.commit()
        await state.clear()
        org_id = r.value.organization_id
        await message.answer(
            f"✅ Организация <b>{r.value.name}</b> создана.\n"
            f"ID: <code>{org_id}</code>\n\n"
            "Выдай инвайт владельцу/админу (без Telegram ID):\n"
            f"<code>/org_invite {org_id} owner</code>\n"
            f"<code>/org_invite {org_id} admin</code>"
        )


def _parse_uuid(text: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(text.strip())
    except Exception:
        return None


@_router.message(Command("org_invite"))
async def org_invite(message: Message) -> None:
    """Super-admin: create an invite for owner/admin/operator without existing users."""
    if message.from_user is None or not _is_super_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 3:
        await message.answer(
            "Использование:\n"
            "<code>/org_invite <org_uuid> <owner|admin|operator> [hours]</code>"
        )
        return
    org_id = _parse_uuid(parts[1])
    if org_id is None:
        await message.answer("org_uuid не распознан.")
        return
    role = parts[2].strip().lower()
    hours: int | None = None
    if len(parts) >= 4:
        try:
            hours = int(parts[3])
        except ValueError:
            hours = None

    factory = get_sessionmaker()
    async with factory() as session:
        uc = CreateSystemInviteUseCase(session)
        r = await uc.execute(
            organization_id=org_id,
            role=role,
            location_id=None,
            expires_in_hours=hours,
        )
        if isinstance(r, Failure):
            await message.answer(f"Не удалось создать инвайт: {r.error.code}")
            await session.rollback()
            return
        assert isinstance(r, Success)
        settings = get_settings()
        uname = settings.tg_bot_username.lstrip("@")
        deep = f"https://t.me/{uname}?start=inv_{r.value.token}"
        await session.commit()
        await message.answer(
            "✅ Инвайт создан.\n"
            f"Роль: <b>{role}</b>\n"
            f"Ссылка: {deep}\n"
            f"Истекает: <code>{r.value.expires_at.isoformat()}</code>"
        )


@_router.message(Command("org_set_owner"))
async def org_set_owner(message: Message) -> None:
    """Super-admin: (re)assign a single owner inside an org by tg_id.

    The user must already exist in the org (e.g. via /org_invite ... admin),
    then we promote them to owner and demote any other owners to admin.
    """

    if message.from_user is None or not _is_super_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 3:
        await message.answer("Использование:\n<code>/org_set_owner <org_uuid> <tg_user_id></code>")
        return
    org_id = _parse_uuid(parts[1])
    if org_id is None:
        await message.answer("org_uuid не распознан.")
        return
    try:
        tg_id = int(parts[2])
    except ValueError:
        await message.answer("tg_user_id должен быть числом.")
        return

    factory = get_sessionmaker()
    async with factory() as session:
        await session.execute(text("SET LOCAL row_security = off"))
        row = (
            await session.execute(
                select(TelegramAccount, User)
                .join(User, User.id == TelegramAccount.user_id)
                .where(TelegramAccount.tg_user_id == tg_id)
                .where(User.organization_id == org_id)
            )
        ).first()
        if row is None:
            await message.answer("Пользователь с таким tg_id не найден в этой организации.")
            return
        _, user = row
        await session.execute(
            text(
                "UPDATE users SET role = 'admin' "
                "WHERE organization_id = :org AND role = 'owner' AND id <> :uid"
            ),
            {"org": str(org_id), "uid": str(user.id)},
        )
        user.role = "owner"
        await session.commit()
        await message.answer(f"✅ Владелец назначен. user_id=<code>{user.id}</code>")


@_router.message(Command("cancel"))
async def cancel_fsm(message: Message, state: FSMContext) -> None:
    if message.from_user and _is_super_admin(message.from_user.id):
        await state.clear()
        await message.answer("Отменено.")


@_router.message(Command("help"))
async def handle_help(message: Message) -> None:
    web_app_url = get_settings().web_public_url
    if message.from_user is not None and _is_super_admin(message.from_user.id):
        await message.answer(
            "<b>ShiftOps · Super admin</b>\n\n"
            "Организации:\n"
            "• <code>/create_org</code> — создать организацию (без владельца)\n"
            "• <code>/org_invite &lt;org_uuid&gt; &lt;owner|admin|operator&gt; [hours]</code> — инвайт-ссылка\n"
            "• <code>/org_set_owner &lt;org_uuid&gt; &lt;tg_user_id&gt;</code> — назначить/переназначить владельца\n\n"
            "Сервис:\n"
            "• <code>/cancel</code> — отменить текущий сценарий\n"
            "• <code>/start</code> — обычный старт\n\n"
            f"Web App: {web_app_url}"
        )
        return

    if message.from_user is None:
        await message.answer(f"<b>ShiftOps</b>\n\nWeb App: {web_app_url}")
        return

    factory = get_sessionmaker()
    async with factory() as session:
        existing = await _existing_tg_user(session, message.from_user.id)

    if existing is None:
        await message.answer(
            "<b>ShiftOps</b>\n\n"
            "Вы ещё не привязаны к организации.\n"
            "Попросите администратора прислать инвайт-ссылку и нажмите её в этом чате.\n\n"
            f"Web App: {web_app_url}\n"
            "Команды:\n"
            "• <code>/start</code> — старт (инвайт-ссылка тоже приходит сюда)\n"
            "• <code>/help</code> — помощь"
        )
        return

    _, user = existing
    role = (user.role or "").lower()
    if role == "owner":
        await message.answer(
            "<b>ShiftOps · Владелец</b>\n\n"
            f"Web App: {web_app_url}\n\n"
            "Действия:\n"
            "• Управление точками/шаблонами/командой — в Web App\n"
            "• Приглашения сотрудникам — в Web App (раздел команды/инвайты)\n\n"
            "Команды:\n"
            "• <code>/start</code>\n"
            "• <code>/help</code>"
        )
        return

    if role == "admin":
        await message.answer(
            "<b>ShiftOps · Администратор</b>\n\n"
            f"Web App: {web_app_url}\n\n"
            "Действия:\n"
            "• Управление шаблонами/командой — в Web App\n\n"
            "Команды:\n"
            "• <code>/start</code>\n"
            "• <code>/help</code>"
        )
        return

    await message.answer(
        "<b>ShiftOps</b>\n\n"
        f"Web App: {web_app_url}\n\n"
        "Команды:\n"
        "• <code>/start</code>\n"
        "• <code>/help</code>\n\n"
        "Если вы ожидаете задачи и ничего не видно — попросите администратора проверить вашу роль."
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
        dp = Dispatcher(storage=_storage)
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
