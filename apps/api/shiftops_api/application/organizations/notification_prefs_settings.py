"""Read / write ``Organization.notification_prefs`` for the current tenant."""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from shiftops_api.application.auth.deps import CurrentUser
from shiftops_api.application.organizations.notification_prefs_config import NotificationPrefsConfig
from shiftops_api.domain.enums import UserRole
from shiftops_api.domain.result import DomainError, Failure, Result, Success
from shiftops_api.infra.db.models import Organization

_log = structlog.get_logger("shiftops.notification_prefs")


class GetNotificationPrefsUseCase:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def execute(self, *, user: CurrentUser) -> NotificationPrefsConfig:
        org = await self._session.get(Organization, user.organization_id)
        if org is None or not org.notification_prefs:
            return NotificationPrefsConfig()
        return NotificationPrefsConfig.parse_storage(
            org.notification_prefs if isinstance(org.notification_prefs, dict) else {}
        )


class SaveNotificationPrefsUseCase:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def execute(
        self,
        *,
        user: CurrentUser,
        payload: NotificationPrefsConfig,
    ) -> Result[NotificationPrefsConfig, DomainError]:
        if user.role != UserRole.OWNER:
            return Failure(DomainError("forbidden", "only the org owner can change notification settings"))

        org = await self._session.get(Organization, user.organization_id)
        if org is None:
            return Failure(DomainError("organization_not_found"))

        org.notification_prefs = payload.to_storage()
        flag_modified(org, "notification_prefs")
        await self._session.commit()
        _log.info(
            "notification_prefs_saved",
            org_id=str(user.organization_id),
            user_id=str(user.id),
        )
        return Success(payload)


__all__ = ["GetNotificationPrefsUseCase", "SaveNotificationPrefsUseCase"]
