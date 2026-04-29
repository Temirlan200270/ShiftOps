"""Use case: accept an invite in the Telegram bot (no JWT — bypasses RLS for writes)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from aiogram import types
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.domain.result import DomainError, Failure, Result, Success
from shiftops_api.infra.db.models import Invite, Location, Organization, TelegramAccount, User


@dataclass(frozen=True, slots=True)
class RedeemOk:
    full_name: str
    role: str
    organization_name: str
    location_label: str | None


def _display_name(tg: types.User) -> str:
    parts = [tg.first_name or "", tg.last_name or ""]
    name = " ".join(p for p in parts if p).strip()
    if name:
        return name
    if tg.username:
        return f"@{tg.username}"
    return "ShiftOps user"


class RedeemInviteUseCase:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def execute(
        self,
        *,
        token: str,
        tg: types.User,
    ) -> Result[RedeemOk, DomainError]:
        await self._session.execute(text("SET LOCAL row_security = off"))

        now = datetime.now(tz=UTC)
        row = (
            await self._session.execute(select(Invite).where(Invite.token == token).limit(1))
        ).scalar_one_or_none()
        if row is None:
            return Failure(DomainError("invite_not_found", "invalid or expired link"))
        if row.used_at is not None:
            return Failure(DomainError("invite_already_used", "this link was already used"))
        if row.expires_at < now:
            return Failure(DomainError("invite_expired", "this link has expired"))

        org = await self._session.get(Organization, row.organization_id)
        if org is None or not org.is_active:
            return Failure(
                DomainError("organization_inactive", "this organization is not available")
            )

        display = _display_name(tg)
        existing_tg = await self._session.get(TelegramAccount, tg.id)
        if existing_tg is not None:
            user_model = await self._session.get(User, existing_tg.user_id)
            if user_model is None:
                await self._session.delete(existing_tg)
                await self._session.flush()
            else:
                if user_model.organization_id != row.organization_id:
                    return Failure(
                        DomainError(
                            "telegram_linked_other_org",
                            "this Telegram is linked to another organization",
                        )
                    )
                if user_model.is_active:
                    return Failure(
                        DomainError(
                            "already_active_member",
                            "already an active member of this organization",
                        )
                    )

                user_model.is_active = True
                user_model.role = row.role
                user_model.full_name = display
                user_model.locale = (tg.language_code or "ru")[:8]
                existing_tg.tg_username = tg.username
                existing_tg.tg_language_code = (tg.language_code or "")[:8] or None
                row.used_at = now
                row.used_by_user_id = user_model.id
                await self._session.flush()

                location_label: str | None = None
                if row.location_id is not None:
                    loc = await self._session.get(Location, row.location_id)
                    if loc is not None:
                        location_label = loc.name

                return Success(
                    RedeemOk(
                        full_name=display,
                        role=row.role,
                        organization_name=org.name,
                        location_label=location_label,
                    )
                )

        new_user = User(
            id=uuid.uuid4(),
            organization_id=row.organization_id,
            role=row.role,
            full_name=display,
            locale=(tg.language_code or "ru")[:8],
            is_active=True,
        )
        self._session.add(new_user)
        await self._session.flush()

        self._session.add(
            TelegramAccount(
                tg_user_id=tg.id,
                user_id=new_user.id,
                tg_username=tg.username,
                tg_language_code=(tg.language_code or "")[:8] or None,
            )
        )
        row.used_at = now
        row.used_by_user_id = new_user.id
        await self._session.flush()

        location_label: str | None = None
        if row.location_id is not None:
            loc = await self._session.get(Location, row.location_id)
            if loc is not None:
                location_label = loc.name

        return Success(
            RedeemOk(
                full_name=display,
                role=row.role,
                organization_name=org.name,
                location_label=location_label,
            )
        )
