"""Super-admin organization deletion — soft schedule with hard purge after retention.

``DeleteOrganizationUseCase`` **schedules** deletion: ``deleted_at`` is set,
``is_active`` becomes false. A daily TaskIQ job (see
``infra.scheduling.tasks.purge_deleted_orgs_tick``) hard-deletes rows whose
``deleted_at`` is older than :attr:`Settings.org_deletion_retention_days`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from shiftops_api.domain.result import DomainError, Failure, Result, Success
from shiftops_api.infra.db.models import Organization
from shiftops_api.infra.db.rls import enter_privileged_rls_mode

_log = structlog.get_logger("shiftops.org.delete")


@dataclass(frozen=True, slots=True)
class OrganizationDeleted:
    organization_id: uuid.UUID
    name: str


class DeleteOrganizationUseCase:
    """Mark an organization as deleted; API/invites stop working immediately."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def execute(self, *, organization_id: uuid.UUID) -> Result[OrganizationDeleted, DomainError]:
        await enter_privileged_rls_mode(self._session, reason="delete_organization")

        org = await self._session.get(Organization, organization_id)
        if org is None:
            return Failure(DomainError("organization_not_found", "organization does not exist"))

        if org.deleted_at is not None:
            return Failure(
                DomainError(
                    "organization_already_deleted",
                    "organization is already scheduled for removal",
                )
            )

        name = org.name
        org.deleted_at = datetime.now(tz=UTC)
        org.is_active = False

        await self._session.flush()

        _log.info("organization_soft_deleted", organization_id=str(organization_id), name=name)
        return Success(OrganizationDeleted(organization_id=organization_id, name=name))


__all__ = ["DeleteOrganizationUseCase", "OrganizationDeleted"]
