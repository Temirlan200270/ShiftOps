"""Super-admin use case: create a tenant and seed the first owner (Telegram-linked)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.domain.enums import UserRole
from shiftops_api.domain.result import DomainError, Failure, Result, Success
from shiftops_api.infra.db.models import Organization, TelegramAccount, User


@dataclass(frozen=True, slots=True)
class OrganizationCreated:
    organization_id: uuid.UUID
    owner_user_id: uuid.UUID
    name: str


class CreateOrganizationUseCase:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def execute(
        self,
        *,
        name: str,
        owner_tg_user_id: int,
        owner_display_name: str,
    ) -> Result[OrganizationCreated, DomainError]:
        cleaned = name.strip()
        if len(cleaned) < 2 or len(cleaned) > 255:
            return Failure(DomainError("invalid_org_name", "name must be 2-255 characters"))

        await self._session.execute(text("SET LOCAL row_security = off"))

        dup = (
            await self._session.execute(
                select(TelegramAccount).where(TelegramAccount.tg_user_id == owner_tg_user_id)
            )
        ).scalar_one_or_none()
        if dup is not None:
            return Failure(
                DomainError("telegram_already_linked", "this Telegram id already has an account")
            )

        org = Organization(
            id=uuid.uuid4(),
            name=cleaned,
            plan="trial",
            is_active=True,
            trial_ends_at=datetime.now(tz=UTC) + timedelta(days=30),
        )
        self._session.add(org)
        await self._session.flush()

        owner = User(
            id=uuid.uuid4(),
            organization_id=org.id,
            role=UserRole.OWNER.value,
            full_name=owner_display_name[:255],
            locale="ru",
            is_active=True,
        )
        self._session.add(owner)
        await self._session.flush()

        self._session.add(
            TelegramAccount(
                tg_user_id=owner_tg_user_id,
                user_id=owner.id,
                tg_username=None,
                tg_language_code=None,
            )
        )
        await self._session.flush()

        return Success(
            OrganizationCreated(
                organization_id=org.id,
                owner_user_id=owner.id,
                name=org.name,
            )
        )
