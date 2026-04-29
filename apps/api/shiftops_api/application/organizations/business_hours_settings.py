"""Read / write ``Organization.business_hours`` for the current tenant."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.application.organizations.business_hours_config import BusinessHoursConfig
from shiftops_api.domain.enums import UserRole
from shiftops_api.domain.result import DomainError, Failure, Result, Success
from shiftops_api.infra.db.models import Organization


class GetBusinessHoursUseCase:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def execute(self, *, user: CurrentUser) -> BusinessHoursConfig:
        org = await self._session.get(Organization, user.organization_id)
        if org is None:
            return BusinessHoursConfig()
        raw = org.business_hours
        if raw is None:
            return BusinessHoursConfig()
        return BusinessHoursConfig.parse_storage(raw if isinstance(raw, dict) else {})


class SaveBusinessHoursUseCase:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def execute(
        self,
        *,
        user: CurrentUser,
        payload: BusinessHoursConfig,
    ) -> Result[None, DomainError]:
        if user.role not in (UserRole.ADMIN, UserRole.OWNER):
            return Failure(DomainError("forbidden"))

        org = await self._session.get(Organization, user.organization_id)
        if org is None:
            return Failure(DomainError("organization_not_found"))

        org.business_hours = payload.to_storage()
        await self._session.commit()
        return Success(None)


__all__ = ["GetBusinessHoursUseCase", "SaveBusinessHoursUseCase"]
