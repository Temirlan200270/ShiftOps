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

import html
import logging
import uuid
from urllib.parse import urlparse

import structlog
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import DefaultKeyBuilder, RedisStorage
from aiogram.types import (
    CallbackQuery,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    Update,
    WebAppInfo,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.application.invites.create_system_invite import CreateSystemInviteUseCase
from shiftops_api.application.invites.redeem_invite import RedeemInviteUseCase
from shiftops_api.application.organizations.create_organization import (
    CreateOrganizationUseCase,
)
from shiftops_api.application.organizations.delete_organization import (
    DeleteOrganizationUseCase,
)
from shiftops_api.application.organizations.resolve_org_spec import resolve_org_spec_to_uuid
from shiftops_api.application.shifts.approve_waiver import ApproveWaiverUseCase
from shiftops_api.application.team.change_member_role import ChangeMemberRoleUseCase
from shiftops_api.application.team.deactivate_member import DeactivateMemberUseCase
from shiftops_api.config import get_settings
from shiftops_api.domain.enums import UserRole
from shiftops_api.domain.result import Failure, Success
from shiftops_api.infra.db.engine import get_sessionmaker
from shiftops_api.infra.db.models import TelegramAccount, User
from shiftops_api.infra.db.rls import enter_privileged_rls_mode
from shiftops_api.infra.telegram.bot_profile import (
    SlashMenuProfile,
    push_slash_menu_for_private_chat,
)

_log = logging.getLogger(__name__)
_start_log = structlog.get_logger("shiftops.telegram.start")
_fsm_storage_singleton: BaseStorage | None = None
_router = Router()


def _get_fsm_storage() -> BaseStorage:
    global _fsm_storage_singleton
    if _fsm_storage_singleton is None:
        try:
            _fsm_storage_singleton = RedisStorage.from_url(
                get_settings().redis_url,
                key_builder=DefaultKeyBuilder(
                    with_bot_id=True,
                    with_destiny=True,
                ),
            )
        except Exception:
            _log.warning("telegram.fsm.redis_unavailable_fallback_memory", exc_info=True)
            _fsm_storage_singleton = MemoryStorage()
    return _fsm_storage_singleton


def _is_valid_telegram_web_app_url(url: str) -> bool:
    """Telegram rejects WebApp buttons with http://, localhost, or non-public hosts."""
    parsed = urlparse((url or "").strip())
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    if host in ("localhost", "127.0.0.1", "::1") or host.startswith("127."):
        return False
    return bool(host)


def _web_app_entry_keyboard() -> ReplyKeyboardMarkup | None:
    """One-tap open of the TWA after onboarding; avoids users hunting the menu."""
    url = (get_settings().web_public_url or "").strip()
    if not _is_valid_telegram_web_app_url(url):
        if url:
            _start_log.warning("web_app_entry_keyboard_skipped_invalid_url", url=url)
        return None
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Открыть ShiftOps", web_app=WebAppInfo(url=url))]],
        resize_keyboard=True,
    )


class CreateOrgFSM(StatesGroup):
    org_name = State()


def _bot() -> Bot:
    return Bot(
        token=get_settings().tg_bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def _command_head_token(text: str) -> str:
    """First token of a message, command part without @bot suffix."""
    parts = (text or "").strip().split(maxsplit=1)
    if not parts:
        return ""
    head = parts[0]
    if "@" in head:
        head = head.split("@", 1)[0]
    return head


def _is_cancel_command_text(text: str) -> bool:
    return _command_head_token(text).lower() == "/cancel"


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
    has_inv = payload.startswith("inv_") and len(payload) > len("inv_")
    _start_log.info(
        "start_command",
        tg_user_id=message.from_user.id,
        has_invite_payload=has_inv,
        payload_chars=len(payload),
    )
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
            use_case = RedeemInviteUseCase(session)
            result = await use_case.execute(token=token, tg=message.from_user)
            if isinstance(result, Failure):
                messages = {
                    "invite_not_found": "Ссылка недействительна или устарела.",
                    "invite_expired": "Срок ссылки истёк. Попросите новую у администратора.",
                    "invite_already_used": "Эта ссылка уже использована.",
                    "organization_inactive": "Организация не активна. Обратитесь в поддержку.",
                    "telegram_linked_other_org": (
                        "Этот Telegram уже привязан к другой организации в ShiftOps. "
                        "Нужна отдельная учётная запись или обратитесь в поддержку."
                    ),
                    "already_active_member": (
                        "Вы уже участник этой организации — откройте Web App, новая ссылка не нужна."
                    ),
                    "telegram_already_linked": (
                        "Этот Telegram уже используется в ShiftOps в неожиданном состоянии. "
                        "Обратитесь к администратору или в поддержку."
                    ),
                }
                text = messages.get(
                    result.error.code,
                    "Не удалось принять приглашение. Попросите администратора выдать новую ссылку.",
                )
                if result.error.code == "already_active_member" and existing is not None:
                    await _push_slash_menu(message, existing[1])
                    already_kb = _web_app_entry_keyboard()
                    already_hint = (
                        "откройте приложение кнопкой ниже."
                        if already_kb
                        else "откройте мини-приложение через меню бота."
                    )
                    await message.answer(
                        f"Вы уже в организации — {already_hint}",
                        reply_markup=already_kb,
                    )
                else:
                    await message.answer(text)
                _start_log.warning(
                    "invite_redeem_failed",
                    tg_user_id=message.from_user.id,
                    code=result.error.code,
                )
                await session.rollback()
                return
            assert isinstance(result, Success)
            _start_log.info(
                "invite_redeemed",
                tg_user_id=message.from_user.id,
                organization_name=result.value.organization_name,
                role=result.value.role,
            )
            loc_line = (
                f"Вас пригласили в точку: <b>{result.value.location_label}</b>.\n"
                if result.value.location_label
                else ""
            )
            welcome_kb = _web_app_entry_keyboard()
            open_hint = (
                "<b>Сначала нажмите кнопку «Открыть ShiftOps» ниже</b> "
                "(или пункт меню бота с мини-приложением) — так Telegram передаст нам ваш профиль."
                if welcome_kb
                else "<b>Откройте мини-приложение</b> через меню бота (кнопка слева от поля ввода "
                "или в профиле бота) — так Telegram передаст нам ваш профиль. "
                "Если кнопки нет, администратору нужно задать публичный HTTPS URL TWA на сервере."
            )
            await message.answer(
                f"✅ Добро пожаловать в <b>{result.value.organization_name}</b>.\n"
                f"{loc_line}"
                f"Ваша роль: <b>{result.value.role}</b>.\n"
                f"{open_hint}",
                reply_markup=welcome_kb,
            )
            await session.commit()
            joined = await _existing_tg_user(session, message.from_user.id)
            await _push_slash_menu(message, joined[1] if joined else None)
            return

        if payload.startswith("swap_req_"):
            raw = payload.removeprefix("swap_req_").strip()
            try:
                swap_shift_id = uuid.UUID(raw)
            except ValueError:
                await message.answer("Ссылка на обмен повреждена.")
                return
            web_base = (get_settings().web_public_url or "").strip().rstrip("/")
            if not _is_valid_telegram_web_app_url(web_base):
                await message.answer(
                    "Не задан корректный HTTPS URL мини-приложения. Обратитесь к администратору."
                )
                return
            deep_url = f"{web_base}/?swap_proposer_shift={swap_shift_id}"
            swap_kb = ReplyKeyboardMarkup(
                keyboard=[
                    [
                        KeyboardButton(
                            text="Открыть обмен (ShiftOps)",
                            web_app=WebAppInfo(url=deep_url),
                        )
                    ]
                ],
                resize_keyboard=True,
            )
            if existing is None:
                await message.answer(
                    "🔗 <b>Обмен сменами</b>\n\n"
                    "Чтобы ответить на запрос, сначала примите приглашение в ShiftOps от администратора, "
                    "затем снова откройте эту ссылку из чата.",
                )
                return
            await message.answer(
                "🔗 Коллега предлагает обменяться сменой. Откройте приложение — выберите свою "
                "запланированную смену и отправьте запрос.",
                reply_markup=swap_kb,
            )
            return

        if existing is None:
            web_app_url = get_settings().web_public_url
            await _push_slash_menu(message, None)
            hint = ""
            if not has_inv:
                hint = (
                    "\n\n⚠️ <b>Важно.</b> Если вас пригласили по ссылке, нажимайте <b>именно её</b> "
                    "(или «Start» в сообщении с приглашением). "
                    "Кнопка «Start» в профиле бота без ссылки даёт только этот текст — "
                    "<b>инвайт так не активируется</b> и в базе вас ещё нет."
                )
            _start_log.info("start_plain_guest", tg_user_id=message.from_user.id, had_inv=has_inv)
            await message.answer(
                "👋 Добро пожаловать в <b>ShiftOps</b>.\n\n"
                "Чтобы попасть в команду заведения, откройте <b>одноразовую ссылку-приглашение</b>, "
                "которую прислал администратор (в Telegram она выглядит как переход к этому боту "
                "с параметром start). После успешного входа вы увидите сообщение "
                "«✅ Добро пожаловать в <i>название организации</i>» — только тогда открывайте "
                "мини-приложение."
                f"{hint}\n\n"
                f"Справка по приложению: {web_app_url}",
            )
            return
        _, user = existing
        await _push_slash_menu(message, user)
        back_kb = _web_app_entry_keyboard()
        _start_log.info(
            "start_returning_member",
            tg_user_id=message.from_user.id,
            user_id=str(user.id),
        )
        back_greet = (
            f"С возвращением, {user.full_name}. Откройте ShiftOps кнопкой ниже или через меню бота."
            if back_kb
            else f"С возвращением, {user.full_name}. Откройте ShiftOps через меню бота (мини-приложение)."
        )
        await message.answer(back_greet, reply_markup=back_kb)


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
    factory_co = get_sessionmaker()
    async with factory_co() as session_co:
        ex_co = await _existing_tg_user(session_co, message.from_user.id)
    await _push_slash_menu(message, ex_co[1] if ex_co else None)
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
    if _is_cancel_command_text(message.text):
        await state.clear()
        await message.answer("Создание организации отменено.")
        return
    name = message.text.strip()
    if name.startswith("/"):
        await message.answer(
            "Это похоже на команду, а не на название. "
            "Введите название организации текстом или отправьте <code>/cancel</code> для отмены."
        )
        return
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
        safe_name = html.escape(r.value.name)
        await message.answer(
            f"✅ Организация <b>{safe_name}</b> создана.\n"
            f"ID: <code>{org_id}</code>\n\n"
            "Выдай инвайт владельцу/админу (Telegram ID в команду не нужен):\n"
            f"<code>/org_invite {safe_name} owner</code>\n"
            f"<code>/org_invite {safe_name} admin</code>\n\n"
            "Или по UUID:\n"
            f"<code>/org_invite {org_id} owner</code>"
        )


def _parse_uuid(text: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(text.strip())
    except Exception:
        return None


def _command_argv(message: Message) -> list[str]:
    """Tokens after the command (``/foo bar`` → ``[\"bar\"]``)."""

    t = (message.text or "").strip()
    if not t:
        return []
    parts = t.split()
    if len(parts) < 2:
        return []
    head = parts[0]
    if "@" in head:
        head = head.split("@", 1)[0]
    if not head.startswith("/"):
        return []
    return parts[1:]


_ORG_INVITE_ROLES = frozenset({"owner", "admin", "operator", "bartender"})
_MAX_INVITE_HOURS = 168


def _parse_org_invite_argv(
    tokens: list[str],
) -> tuple[str, str, int | None, int | None]:
    """``org … role`` or ``org … role hours`` where hours must be 1..168.

    Returns ``(org_spec, role, hours, stray_numeric_hint)`` — if the user
    passes a Telegram user id in the last slot, ``hours`` is ``None`` and
    ``stray_numeric_hint`` carries the number for the hint text.
    """

    if len(tokens) < 2:
        raise ValueError("usage")
    last = tokens[-1]
    if last.lower() in _ORG_INVITE_ROLES:
        org_spec = " ".join(tokens[:-1]).strip()
        role = last.lower()
        if not org_spec:
            raise ValueError("usage")
        return org_spec, role, None, None
    if len(tokens) < 3:
        raise ValueError("usage")
    second_last = tokens[-2]
    if second_last.lower() not in _ORG_INVITE_ROLES:
        raise ValueError("usage")
    if not last.isdigit():
        raise ValueError("usage")
    n = int(last)
    org_spec = " ".join(tokens[:-2]).strip()
    role = second_last.lower()
    if not org_spec:
        raise ValueError("usage")
    if 1 <= n <= _MAX_INVITE_HOURS:
        return org_spec, role, n, None
    return org_spec, role, None, n


def _parse_org_plus_trailing_tg(tokens: list[str]) -> tuple[str, int] | None:
    if len(tokens) < 2 or not tokens[-1].isdigit():
        return None
    tg = int(tokens[-1])
    if tg < 1:
        return None
    org_spec = " ".join(tokens[:-1]).strip()
    if not org_spec:
        return None
    return org_spec, tg


def _parse_org_tg_role(tokens: list[str]) -> tuple[str, int, str] | None:
    if len(tokens) < 3:
        return None
    role = tokens[-1].lower()
    if role not in {"admin", "operator", "bartender"}:
        return None
    if not tokens[-2].isdigit():
        return None
    tg = int(tokens[-2])
    org_spec = " ".join(tokens[:-2]).strip()
    if not org_spec:
        return None
    return org_spec, tg, role


async def _push_slash_menu(message: Message, user: User | None) -> None:
    """Refresh Telegram slash hints for this private chat."""

    if message.from_user is None or message.chat is None:
        return
    bot = message.bot
    if bot is None:
        return
    chat_id = message.chat.id
    if _is_super_admin(message.from_user.id):
        profile = SlashMenuProfile.SUPER_ADMIN
    elif user is None:
        profile = SlashMenuProfile.GUEST
    elif user.role == UserRole.OWNER:
        profile = SlashMenuProfile.OWNER
    elif user.role == UserRole.ADMIN:
        profile = SlashMenuProfile.ADMIN
    else:
        profile = SlashMenuProfile.LINE
    await push_slash_menu_for_private_chat(bot, chat_id=chat_id, profile=profile)


@_router.message(Command("org_invite"))
async def org_invite(message: Message) -> None:
    """Super-admin: create an invite for owner/admin/operator/bartender without existing users."""
    if message.from_user is None or not _is_super_admin(message.from_user.id):
        return
    tokens = _command_argv(message)
    if not tokens:
        await message.answer(
            "Использование:\n"
            "<code>/org_invite &lt;название или UUID&gt; &lt;owner|admin|operator|bartender&gt; [1–168 ч]</code>\n\n"
            "Примеры:\n"
            "<code>/org_invite PlovХана owner</code>\n"
            "<code>/org_invite The Rusty Anchor admin 72</code>"
        )
        return
    try:
        org_spec, role, hours, stray_num = _parse_org_invite_argv(tokens)
    except ValueError:
        await message.answer(
            "Не разобрал аргументы.\n"
            "<code>/org_invite &lt;название или UUID&gt; &lt;роль&gt; [часы 1–168]</code>\n\n"
            "<i>Не добавляйте Telegram ID в эту команду</i> — только срок жизни ссылки (часы) "
            "или ничего."
        )
        return

    factory = get_sessionmaker()
    async with factory() as session:
        org_id, err = await resolve_org_spec_to_uuid(session, org_spec)
        if org_id is None:
            await message.answer(err or "Организация не найдена.")
            return
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
        hint = ""
        if stray_num is not None:
            hint = (
                "\n\n<i>В конце было число <code>"
                f"{stray_num}</code> — это не срок ссылки (допустимо 1–{_MAX_INVITE_HOURS} часов).</i>\n"
                "Инвайту не нужен Telegram ID получателя. Создана ссылка со стандартным сроком (48 ч)."
            )
        await message.answer(
            "✅ Инвайт создан.\n"
            f"Роль: <b>{role}</b>\n"
            f"Ссылка: {deep}\n"
            f"Истекает: <code>{r.value.expires_at.isoformat()}</code>"
            f"{hint}"
        )


@_router.message(Command("org_delete"))
async def org_delete_for_super_admin(message: Message) -> None:
    """Super-admin: hard-delete a tenant; resolves org by exact name (case-insensitive) or UUID."""

    if message.from_user is None or not _is_super_admin(message.from_user.id):
        return
    tokens = _command_argv(message)
    if not tokens:
        await message.answer(
            "Использование:\n"
            "<code>/org_delete &lt;название или UUID&gt;</code>\n\n"
            "Помечает организацию на удаление: доступ TWA/инвайты отключаются сразу, "
            f"а строки в БД <b>безвозвратно</b> удалятся через "
            f"<code>{get_settings().org_deletion_retention_days}</code> дней.\n\n"
            "Примеры:\n"
            "<code>/org_delete PlovХана</code>\n"
            "<code>/org_delete The Rusty Anchor</code>\n"
            "<code>/org_delete 51794cbb-8b0a-47bb-84cf-1c619a275057</code>"
        )
        return
    org_spec = " ".join(tokens).strip()

    factory = get_sessionmaker()
    async with factory() as session:
        org_id, err = await resolve_org_spec_to_uuid(session, org_spec)
        if org_id is None:
            await message.answer(err or "Организация не найдена.")
            return
        uc = DeleteOrganizationUseCase(session)
        result = await uc.execute(organization_id=org_id)
        if isinstance(result, Failure):
            await message.answer(f"Не удалось удалить: <code>{html.escape(result.error.code)}</code>")
            await session.rollback()
            return
        assert isinstance(result, Success)
        await session.commit()
        safe = html.escape(result.value.name)
        retention = get_settings().org_deletion_retention_days
        await message.answer(
            f"🗑 Организация <b>{safe}</b> (<code>{result.value.organization_id}</code>) "
            f"отмечена на удаление. Данные будут стёрты безвозвратно через <b>{retention}</b> дн."
        )


@_router.message(Command("org_set_owner"))
async def org_set_owner(message: Message) -> None:
    """Super-admin: (re)assign a single owner inside an org by tg_id.

    The user must already exist in the org (e.g. via /org_invite ... admin),
    then we promote them to owner and demote any other owners to admin.
    """

    if message.from_user is None or not _is_super_admin(message.from_user.id):
        return
    tokens = _command_argv(message)
    parsed = _parse_org_plus_trailing_tg(tokens)
    if parsed is None:
        await message.answer(
            "Использование:\n"
            "<code>/org_set_owner &lt;название или UUID&gt; &lt;tg_user_id&gt;</code>"
        )
        return
    org_spec, tg_id = parsed

    factory = get_sessionmaker()
    async with factory() as session:
        org_id, err = await resolve_org_spec_to_uuid(session, org_spec)
        if org_id is None:
            await message.answer(err or "Организация не найдена.")
            return
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
        user.role = UserRole.OWNER
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
    user_for_menu: User | None = None
    if message.from_user is not None:
        factory_menu = get_sessionmaker()
        async with factory_menu() as session_menu:
            ex_menu = await _existing_tg_user(session_menu, message.from_user.id)
        if ex_menu is not None:
            user_for_menu = ex_menu[1]
    await _push_slash_menu(message, user_for_menu)

    if message.from_user is not None and _is_super_admin(message.from_user.id):
        await message.answer(
            "<b>ShiftOps · Super admin</b>\n\n"
            "Во всех командах ниже вместо UUID можно указать <b>точное название</b> организации "
            "(как после <code>/create_org</code>). Несколько слов — подряд, без кавычек.\n"
            "В <code>/org_invite</code> не передавайте Telegram ID: только роль и опционально "
            f"срок ссылки в часах (1–{_MAX_INVITE_HOURS}).\n\n"
            "Организации:\n"
            "• <code>/create_org</code> — создать организацию (без владельца)\n"
            "• <code>/org_invite &lt;название|UUID&gt; &lt;owner|admin|operator|bartender&gt; [часы]</code> — инвайт-ссылка\n"
            "• <code>/org_delete &lt;название|UUID&gt;</code> — пометить организацию на удаление "
            f"(безвозвратное стирание через {get_settings().org_deletion_retention_days} дн.)\n"
            "• <code>/org_set_owner &lt;название|UUID&gt; &lt;tg_user_id&gt;</code> — назначить/переназначить владельца\n"
            "• <code>/org_set_role &lt;название|UUID&gt; &lt;tg_user_id&gt; &lt;admin|operator|bartender&gt;</code> — сменить роль участника\n"
            "• <code>/org_remove_member &lt;название|UUID&gt; &lt;tg_user_id&gt;</code> — деактивировать участника\n\n"
            "Сервис:\n"
            "• <code>/cancel</code> — отменить текущий сценарий\n"
            "• <code>/start</code> — обычный старт\n\n"
            "Подсказки команд при вводе <code>/</code> обновляются после <code>/start</code> и <code>/help</code>.\n\n"
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
    role = (user.role.value or "").lower()
    if role == "owner":
        await message.answer(
            "<b>ShiftOps · Владелец</b>\n\n"
            f"Web App: {web_app_url}\n\n"
            "Команда:\n"
            "• <code>/team_list</code> — список участников + кнопки «изменить роль/удалить»\n"
            "• <code>/set_role &lt;@username|tg_id&gt; &lt;admin|operator|bartender&gt;</code> — сменить роль\n"
            "• <code>/remove_member &lt;@username|tg_id&gt;</code> — удалить (деактивировать) участника\n\n"
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
            "• Просмотр команды/шаблонов — в Web App\n"
            "• Изменение ролей и удаление участников — только владелец/супер-админ\n\n"
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


async def _resolve_owner_actor(
    session: AsyncSession, tg_user_id: int
) -> tuple[CurrentUser, User] | None:
    """Find an owner record by Telegram id (RLS bypass).

    Returns ``(actor, owner_user)`` so callers can construct a
    :class:`CurrentUser` with the right org context, or ``None`` if the user
    is not an owner of any active org. Sets ``app.org_id`` for downstream RLS.
    """

    await enter_privileged_rls_mode(session, reason="telegram_bot_resolve_owner_actor")
    row = (
        await session.execute(
            select(User)
            .join(TelegramAccount, TelegramAccount.user_id == User.id)
            .where(TelegramAccount.tg_user_id == tg_user_id)
            .where(User.role == UserRole.OWNER)
            .where(User.is_active.is_(True))
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    actor = CurrentUser(
        id=row.id,
        organization_id=row.organization_id,
        role=UserRole.OWNER,
        tg_user_id=tg_user_id,
    )
    return actor, row


def _strip_username(token: str) -> str:
    return token.lstrip("@").strip()


async def _resolve_target_user(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    raw: str,
) -> User | None:
    """Resolve `@username` or numeric `tg_user_id` to a User row in *org*.

    Falls back to ``None`` when nothing matches; callers turn that into a
    user-friendly error in the bot reply.
    """

    raw = raw.strip()
    if not raw:
        return None
    tg_user_id: int | None
    try:
        tg_user_id = int(raw)
    except ValueError:
        tg_user_id = None

    stmt = (
        select(User)
        .join(TelegramAccount, TelegramAccount.user_id == User.id)
        .where(User.organization_id == organization_id)
    )
    if tg_user_id is not None:
        stmt = stmt.where(TelegramAccount.tg_user_id == tg_user_id)
    else:
        username = _strip_username(raw)
        if not username:
            return None
        stmt = stmt.where(TelegramAccount.tg_username == username)
    return (await session.execute(stmt)).scalar_one_or_none()


_TEAM_ERR_MESSAGES: dict[str, str] = {
    "user_not_found": "Пользователь не найден в этой организации.",
    "cannot_manage_self": "Нельзя выполнить действие над самим собой.",
    "cannot_manage_super_admin": "Этого пользователя нельзя менять на уровне организации.",
    "insufficient_role": "Недостаточно прав. Только владелец или супер-админ.",
    "cannot_change_owner_role": "Роль владельца меняется только через /org_set_owner.",
    "already_inactive": "Пользователь уже деактивирован.",
    "invalid_target_role": "Допустимые роли: admin, operator, bartender.",
}


def _team_err_text(code: str) -> str:
    return _TEAM_ERR_MESSAGES.get(code, f"Ошибка: {code}")


@_router.message(Command("team_list"))
async def team_list_for_owner(message: Message) -> None:
    if message.from_user is None:
        return
    if _is_super_admin(message.from_user.id):
        await message.answer(
            "Используйте <code>/org_set_role</code> или <code>/org_remove_member</code> "
            "с указанием организации (название или UUID)."
        )
        return
    factory = get_sessionmaker()
    async with factory() as session:
        bound = await _resolve_owner_actor(session, message.from_user.id)
        if bound is None:
            await message.answer("Команда доступна только владельцам организации.")
            return
        actor, _ = bound
        rows = (
            await session.execute(
                select(User, TelegramAccount.tg_user_id, TelegramAccount.tg_username)
                .outerjoin(TelegramAccount, TelegramAccount.user_id == User.id)
                .where(User.organization_id == actor.organization_id)
                .where(User.is_active.is_(True))
                .order_by(User.full_name.asc(), User.role.asc())
            )
        ).all()

    if not rows:
        await message.answer("В команде только вы.")
        return

    lines: list[str] = ["<b>Команда</b>:"]
    for r in rows:
        u, tg_id, tg_username = r[0], r[1], r[2]
        handle = f"@{tg_username}" if tg_username else (str(tg_id) if tg_id else "—")
        lines.append(f"• <b>{u.full_name}</b> · {u.role} · {handle}")
    lines.append(
        "\n<i>Чтобы изменить роль:</i> <code>/set_role &lt;@username|tg_id&gt; &lt;admin|operator|bartender&gt;</code>"
    )
    lines.append("<i>Чтобы удалить:</i> <code>/remove_member &lt;@username|tg_id&gt;</code>")
    await message.answer("\n".join(lines))


@_router.message(Command("set_role"))
async def set_role_for_owner(message: Message) -> None:
    if message.from_user is None:
        return
    parts = (message.text or "").split()
    if len(parts) < 3:
        await message.answer(
            "Использование:\n<code>/set_role &lt;@username|tg_user_id&gt; &lt;admin|operator|bartender&gt;</code>"
        )
        return
    raw_target, raw_role = parts[1], parts[2].lower()
    if raw_role not in {"admin", "operator", "bartender"}:
        await message.answer("Допустимые роли: <b>admin</b>, <b>operator</b>, <b>bartender</b>.")
        return

    factory = get_sessionmaker()
    async with factory() as session:
        bound = await _resolve_owner_actor(session, message.from_user.id)
        if bound is None:
            await message.answer("Команда доступна только владельцам организации.")
            return
        actor, _ = bound
        target = await _resolve_target_user(
            session, organization_id=actor.organization_id, raw=raw_target
        )
        if target is None:
            await message.answer(_team_err_text("user_not_found"))
            return
        uc = ChangeMemberRoleUseCase(session)
        result = await uc.execute(actor=actor, target_user_id=target.id, new_role=raw_role)
        if isinstance(result, Failure):
            await message.answer(_team_err_text(result.error.code))
            await session.rollback()
            return
        assert isinstance(result, Success)
        await session.commit()
        suffix = " (без изменений)" if result.value.no_op else ""
        await message.answer(
            f"✅ Роль обновлена{suffix}: <b>{target.full_name}</b> → <b>{result.value.role}</b>"
        )


@_router.message(Command("remove_member"))
async def remove_member_for_owner(message: Message) -> None:
    if message.from_user is None:
        return
    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer(
            "Использование:\n<code>/remove_member &lt;@username|tg_user_id&gt;</code>"
        )
        return
    raw_target = parts[1]

    factory = get_sessionmaker()
    async with factory() as session:
        bound = await _resolve_owner_actor(session, message.from_user.id)
        if bound is None:
            await message.answer("Команда доступна только владельцам организации.")
            return
        actor, _ = bound
        target = await _resolve_target_user(
            session, organization_id=actor.organization_id, raw=raw_target
        )
        if target is None:
            await message.answer(_team_err_text("user_not_found"))
            return
        uc = DeactivateMemberUseCase(session)
        result = await uc.execute(actor=actor, target_user_id=target.id)
        if isinstance(result, Failure):
            await message.answer(_team_err_text(result.error.code))
            await session.rollback()
            return
        assert isinstance(result, Success)
        await session.commit()
        await message.answer(f"✅ Удалён: <b>{target.full_name}</b>")


@_router.message(Command("org_set_role"))
async def org_set_role_for_super_admin(message: Message) -> None:
    if message.from_user is None or not _is_super_admin(message.from_user.id):
        return
    tokens = _command_argv(message)
    parsed = _parse_org_tg_role(tokens)
    if parsed is None:
        await message.answer(
            "Использование:\n"
            "<code>/org_set_role &lt;название или UUID&gt; &lt;tg_user_id&gt; &lt;admin|operator|bartender&gt;</code>"
        )
        return
    org_spec, tg_id, raw_role = parsed
    if raw_role not in {"admin", "operator", "bartender"}:
        await message.answer("Допустимые роли: <b>admin</b>, <b>operator</b>, <b>bartender</b>.")
        return

    factory = get_sessionmaker()
    async with factory() as session:
        org_id, err = await resolve_org_spec_to_uuid(session, org_spec)
        if org_id is None:
            await message.answer(err or "Организация не найдена.")
            return
        target = await _resolve_target_user(session, organization_id=org_id, raw=str(tg_id))
        if target is None:
            await message.answer(_team_err_text("user_not_found"))
            return
        actor = CurrentUser(
            id=uuid.uuid4(),
            organization_id=org_id,
            role=UserRole.OWNER,
            tg_user_id=message.from_user.id,
        )
        uc = ChangeMemberRoleUseCase(session)
        result = await uc.execute(actor=actor, target_user_id=target.id, new_role=raw_role)
        if isinstance(result, Failure):
            await message.answer(_team_err_text(result.error.code))
            await session.rollback()
            return
        assert isinstance(result, Success)
        await session.commit()
        suffix = " (без изменений)" if result.value.no_op else ""
        await message.answer(
            f"✅ Роль обновлена{suffix}: <b>{target.full_name}</b> → <b>{result.value.role}</b>"
        )


@_router.message(Command("org_remove_member"))
async def org_remove_member_for_super_admin(message: Message) -> None:
    if message.from_user is None or not _is_super_admin(message.from_user.id):
        return
    tokens = _command_argv(message)
    parsed = _parse_org_plus_trailing_tg(tokens)
    if parsed is None:
        await message.answer(
            "Использование:\n"
            "<code>/org_remove_member &lt;название или UUID&gt; &lt;tg_user_id&gt;</code>"
        )
        return
    org_spec, tg_id = parsed

    factory = get_sessionmaker()
    async with factory() as session:
        org_id, err = await resolve_org_spec_to_uuid(session, org_spec)
        if org_id is None:
            await message.answer(err or "Организация не найдена.")
            return
        target = await _resolve_target_user(session, organization_id=org_id, raw=str(tg_id))
        if target is None:
            await message.answer(_team_err_text("user_not_found"))
            return
        actor = CurrentUser(
            id=uuid.uuid4(),
            organization_id=org_id,
            role=UserRole.OWNER,
            tg_user_id=message.from_user.id,
        )
        uc = DeactivateMemberUseCase(session)
        result = await uc.execute(actor=actor, target_user_id=target.id)
        if isinstance(result, Failure):
            await message.answer(_team_err_text(result.error.code))
            await session.rollback()
            return
        assert isinstance(result, Success)
        await session.commit()
        await message.answer(f"✅ Удалён: <b>{target.full_name}</b>")


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
                .where(User.role.in_((UserRole.OWNER, UserRole.ADMIN)))
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
        dp = Dispatcher(storage=_get_fsm_storage())
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
