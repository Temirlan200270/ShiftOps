"""Read / write ``Organization.business_hours`` for the current tenant."""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.application.organizations.business_hours_config import BusinessHoursConfig
from shiftops_api.domain.enums import UserRole
from shiftops_api.domain.result import DomainError, Failure, Result, Success
from shiftops_api.infra.db.models import Organization

_log = structlog.get_logger("shiftops.business_hours")


class GetBusinessHoursUseCase:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def execute(self, *, user: CurrentUser) -> BusinessHoursConfig:
        org = await self._session.get(Organization, user.organization_id)
        if org is None:
            _log.warning(
                "business_hours_loaded",
                org_id=str(user.organization_id),
                user_id=str(user.id),
                empty=True,
                reason="organization_not_found",
            )
            return BusinessHoursConfig()
        raw = org.business_hours
        if raw is None:
            _log.info(
                "business_hours_loaded",
                org_id=str(user.organization_id),
                user_id=str(user.id),
                empty=True,
            )
            return BusinessHoursConfig()
        cfg = BusinessHoursConfig.parse_storage(raw if isinstance(raw, dict) else {})
        _log.info(
            "business_hours_loaded",
            org_id=str(user.organization_id),
            user_id=str(user.id),
            empty=False,
            regular_rows=len(cfg.regular),
            dated_rows=len(cfg.dated),
        )
        return cfg


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
            _log.warning(
                "business_hours_save_denied",
                org_id=str(user.organization_id),
                user_id=str(user.id),
                code="forbidden",
            )
            return Failure(DomainError("forbidden"))

        org = await self._session.get(Organization, user.organization_id)
        if org is None:
            _log.warning(
                "business_hours_save_denied",
                org_id=str(user.organization_id),
                user_id=str(user.id),
                code="organization_not_found",
            )
            return Failure(DomainError("organization_not_found"))

        org.business_hours = payload.to_storage()
        # JSONB assignments sometimes skip change detection; force UPDATE of the column.
        flag_modified(org, "business_hours")
        await self._session.commit()
        _log.info(
            "business_hours_saved",
            org_id=str(user.organization_id),
            user_id=str(user.id),
            regular_rows=len(payload.regular),
            dated_rows=len(payload.dated),
        )
        return Success(None)


__all__ = ["GetBusinessHoursUseCase", "SaveBusinessHoursUseCase"]
