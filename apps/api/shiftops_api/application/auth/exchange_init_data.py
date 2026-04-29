"""Use-case: exchange a Telegram initData payload for a JWT pair.

Steps:
1. Validate signature + auth_date via :class:`InitDataValidator`.
2. Look up the linked `telegram_accounts` row -> `users` row.
3. Mint access + refresh JWTs.
4. Update `tg_username` / `tg_language_code` if changed.

Failure modes (returned as `AuthFailure`):
- ``invalid_init_data``: HMAC mismatch, replay, malformed payload.
- ``ask_admin_to_invite``: the Telegram user has no linked seat.
- ``user_inactive``: linked but `is_active = false`.

Note on RLS: this use-case must read across tenants (we don't know the
organization yet at this point). It calls :func:`enter_privileged_rls_mode`.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.config import get_settings
from shiftops_api.domain.entities import User
from shiftops_api.domain.enums import UserRole
from shiftops_api.infra.auth.jwt_service import JwtService
from shiftops_api.infra.db.models import TelegramAccount
from shiftops_api.infra.db.models import User as UserModel
from shiftops_api.infra.db.rls import enter_privileged_rls_mode
from shiftops_api.infra.telegram.init_data import (
    InitDataValidator,
    InvalidInitData,
    ValidatedInitData,
)


@dataclass(frozen=True, slots=True)
class AuthSuccess:
    user: User
    access_token: str
    refresh_token: str


@dataclass(frozen=True, slots=True)
class AuthFailure:
    reason: str


AuthResult = AuthSuccess | AuthFailure


class ExchangeInitDataUseCase:
    def __init__(
        self,
        *,
        validator: InitDataValidator,
        session: AsyncSession,
        jwt_service: JwtService | None = None,
    ) -> None:
        self._validator = validator
        self._session = session
        self._jwt = jwt_service or JwtService()

    async def execute(self, init_data: str) -> AuthResult:
        try:
            parsed: ValidatedInitData = self._validator.validate(init_data)
        except InvalidInitData as exc:
            return AuthFailure(reason=f"invalid_init_data: {exc}")

        # Bypass RLS for the auth lookup — we don't know the org yet, and the
        # bot token + HMAC signature already authorise us.
        await enter_privileged_rls_mode(self._session, reason="exchange_init_data")

        stmt = (
            select(UserModel, TelegramAccount)
            .join(TelegramAccount, TelegramAccount.user_id == UserModel.id)
            .where(TelegramAccount.tg_user_id == parsed.user.id)
        )
        row = (await self._session.execute(stmt)).first()
        if row is None:
            return AuthFailure(reason="ask_admin_to_invite")

        user_model, tg_account = row
        if not user_model.is_active:
            return AuthFailure(reason="user_inactive")

        # Refresh denormalised TG fields if changed.
        if (
            tg_account.tg_username != parsed.user.username
            or tg_account.tg_language_code != parsed.user.language_code
        ):
            tg_account.tg_username = parsed.user.username
            tg_account.tg_language_code = parsed.user.language_code
            await self._session.flush()

        domain_user = User(
            id=user_model.id,
            organization_id=user_model.organization_id,
            role=UserRole(user_model.role),
            full_name=user_model.full_name,
            locale=user_model.locale,
            tg_user_id=tg_account.tg_user_id,
            is_active=user_model.is_active,
        )

        access = self._jwt.mint_access(
            user_id=domain_user.id,
            org_id=domain_user.organization_id,
            role=domain_user.role,
            tg_user_id=parsed.user.id,
        )
        refresh = self._jwt.mint_refresh(
            user_id=domain_user.id,
            org_id=domain_user.organization_id,
            role=domain_user.role,
            tg_user_id=parsed.user.id,
        )
        await self._session.commit()
        return AuthSuccess(user=domain_user, access_token=access, refresh_token=refresh)


def build_validator() -> InitDataValidator:
    """Module-level helper so DI is a single import line in routers."""
    return InitDataValidator(bot_token=get_settings().tg_bot_token.get_secret_value())
