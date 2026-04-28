"""Super-admin use case: create a tenant, optionally seeding the first owner.

Why owner is optional: platform operator may want to create an org first, then
invite/assign an owner via a deep link without manually collecting Telegram IDs.
"""

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
    name: str
    owner_user_id: uuid.UUID | None = None


class CreateOrganizationUseCase:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def execute(
        self,
        *,
        name: str,
        owner_tg_user_id: int | None = None,
        owner_display_name: str | None = None,
    ) -> Result[OrganizationCreated, DomainError]:
        cleaned = name.strip()
        if len(cleaned) < 2 or len(cleaned) > 255:
            return Failure(DomainError("invalid_org_name", "name must be 2-255 characters"))

        await self._session.execute(text("SET LOCAL row_security = off"))

        if owner_tg_user_id is not None:
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

        owner_id: uuid.UUID | None = None
        if owner_tg_user_id is not None:
            display = (owner_display_name or "Owner")[:255]
            owner = User(
                id=uuid.uuid4(),
                organization_id=org.id,
                role=UserRole.OWNER.value,
                full_name=display,
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
            owner_id = owner.id

        return Success(OrganizationCreated(organization_id=org.id, name=org.name, owner_user_id=owner_id))
